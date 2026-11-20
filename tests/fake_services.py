#!/usr/bin/env python3
# Stand-ins for the tests : a Web Push service (the phones' side) and an
# SMS gateway (SMS Gateway for Android's local API).
#
#   fake_services.py keys <dir> <name>...   subscription keys of each "phone"
#                                            -> <dir>/subs.json
#   fake_services.py serve <port> <dir>     serve until killed
#
# POST /push/<name> : checks the VAPID JWT (ES256 signature with the key
# given in k=, audience = this origin, not expired), DECRYPTS the
# aes128gcm body (RFC 8291 / 8188) with the phone's private key, and
# appends {"device", "vapid_ok", "urgency", "payload"} to <dir>/push.jsonl
# -> 201. /push/gone -> 410 (the subscription is gone).
# POST /message : Basic sms:secret -> appends to <dir>/sms.jsonl -> 202 {"id"}.
# GET /message/<id> : its state as the phone reports it : "Delivered" ;
# "Failed" (no SMS permission) for a number listed in <dir>/sms_fail.txt ;
# "Pending" forever (phone off) for one listed in <dir>/sms_stuck.txt.
import base64, json, os, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode()


def unb64u(s):
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def hkdf(salt, ikm, info, n):
    return HKDF(algorithm=hashes.SHA256(), length=n, salt=salt, info=info).derive(ikm)


RAW = serialization.PublicFormat.UncompressedPoint
X962 = serialization.Encoding.X962


def keys(d, names):
    out = {}
    for n in names:
        k = ec.generate_private_key(ec.SECP256R1())
        out[n] = {'p256dh': b64u(k.public_key().public_bytes(X962, RAW)), 'auth': b64u(os.urandom(16)),
                  'priv': k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()).decode()}
    json.dump(out, open(os.path.join(d, 'subs.json'), 'w'))


def serve(port, d):
    subs = json.load(open(os.path.join(d, 'subs.json')))
    origin = 'http://127.0.0.1:%d' % port
    sms_n = [0]
    sms_to = {}

    def listed(name, number):
        try:
            return number in open(os.path.join(d, name), encoding='utf-8').read().split()
        except OSError:
            return False

    def vapid_ok(h):
        try:
            t = h.split('t=')[1].split(',')[0].strip()
            k = h.split('k=')[1].strip()
            head, claims, sig = t.split('.')
            pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(k))
            raw = unb64u(sig)
            der = encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big'))
            pub.verify(der, (head + '.' + claims).encode(), ec.ECDSA(hashes.SHA256()))
            c = json.loads(unb64u(claims))
            if c['aud'] != origin:
                return 'aud %s != %s' % (c['aud'], origin)
            if c['exp'] <= time.time() or c['exp'] > time.time() + 86400:
                return 'exp %s' % c['exp']
            return 'ok' if c.get('sub') else 'no sub'
        except Exception as e:
            return 'bad : %r' % e

    def decrypt(name, body):
        s = subs[name]
        priv = serialization.load_pem_private_key(s['priv'].encode(), None)
        ua_pub, auth = unb64u(s['p256dh']), unb64u(s['auth'])
        salt, idlen = body[:16], body[20]
        as_pub = body[21:21 + idlen]
        ct = body[21 + idlen:]
        shared = priv.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
        ikm = hkdf(auth, shared, b'WebPush: info\x00' + ua_pub + as_pub, 32)
        cek = hkdf(salt, ikm, b'Content-Encoding: aes128gcm\x00', 16)
        nonce = hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)
        pt = AESGCM(cek).decrypt(nonce, ct, None).rstrip(b'\x00')
        assert pt.endswith(b'\x02'), 'no last-record delimiter'
        return json.loads(pt[:-1])

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, code, body=b''):
            self.send_response(code)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            mid = self.path[len('/message/'):] if self.path.startswith('/message/') else ''
            if self.headers.get('Authorization') != 'Basic ' + base64.b64encode(b'sms:secret').decode():
                return self.reply(401)
            if mid not in sms_to:
                return self.reply(404)
            to = sms_to[mid]
            r = {'phoneNumber': to, 'state': 'Delivered'}
            if listed('sms_fail.txt', to):
                r = {'phoneNumber': to, 'state': 'Failed', 'error': 'sendSMS: uid 10023 does not have android.permission.SEND_SMS.'}
            elif listed('sms_stuck.txt', to):
                r = {'phoneNumber': to, 'state': 'Pending'}
            self.reply(200, json.dumps({'id': mid, 'state': r['state'], 'recipients': [r]}).encode())

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            if self.path.startswith('/push/'):
                name = self.path[6:]
                if name == 'gone':
                    return self.reply(410)
                if name not in subs:
                    return self.reply(404)
                try:
                    payload = decrypt(name, raw)
                except Exception as e:
                    return self.reply(400, str(e).encode())
                with open(os.path.join(d, 'push.jsonl'), 'a', encoding='utf-8') as f:
                    f.write(json.dumps({'device': name, 'vapid_ok': vapid_ok(self.headers.get('Authorization', '')),
                                        'urgency': self.headers.get('Urgency', ''), 'payload': payload}, ensure_ascii=False) + '\n')
                return self.reply(201)
            if self.path == '/message':
                if self.headers.get('Authorization') != 'Basic ' + base64.b64encode(b'sms:secret').decode():
                    return self.reply(401)
                m = json.loads(raw)
                sms_n[0] += 1
                sms_to['s-%d' % sms_n[0]] = m['phoneNumbers'][0]
                with open(os.path.join(d, 'sms.jsonl'), 'a', encoding='utf-8') as f:
                    f.write(json.dumps({'to': m['phoneNumbers'][0], 'text': m['textMessage']['text']}, ensure_ascii=False) + '\n')
                return self.reply(202, json.dumps({'id': 's-%d' % sms_n[0]}).encode())
            self.reply(404)

    HTTPServer(('127.0.0.1', port), H).serve_forever()


if sys.argv[1] == 'keys':
    keys(sys.argv[2], sys.argv[3:])
else:
    serve(int(sys.argv[2]), sys.argv[3])
