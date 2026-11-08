"""Temporary encrypted API diagnostic; never sends a campaign."""
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests

from scripts import newsletter_campaign

PUBLIC_KEY = '-----BEGIN PUBLIC KEY-----\nMIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAzDoY/En0fcZFuITJ1K/h\n5HeHzev+LKl8XE14wnTwFwtgiNOG8mwu9zZWFtkKiT1/xi6SZg7XHFOhLF/Lcqnr\nV+2Di5kJhQ/hdLwHkslnkXf50TVXSd4WcCAYQ6/0YCTq5JXiheLPT3+sKX/OPlYt\n+1aMqbWR8AqNhWMLB2iUFLu24Ah6qy5Z1rM3Wxb8yT/Xj4VLlcpVX0qzMD5HYHlf\nzGlaco9T1FlZ5q0hnA4vaFpyiAaZcC+r4cIAQGoT3dR6UjSEDjxyj9a0t19M827x\ntrnFEMk8XAji7wzIgrmLYr+veSAQelihJF7bAsxUHd4J/QGgBj+Puvr10rdsxMJN\n/5FSP3ubWgvJQMOIp92MaA4E7tN2HYnb/62BVKAZROVhRcHMmTtePgScZ91nAKeX\nXF7QhwB+Gm/teq8xvpXXRH733q/0ijlxt7QPkWNIFAzmNQ4h7KAggdHfHb3DxcEC\n8cs2Z9fPIBEARBT6D0FbjwFq4I609EtSpbA5VJmqeJ0aAqs+XWzuzS+EjSSIIqif\nVuqjs7jE80uqt7f6QencR2V6BBOEqSadvmWAAiVdJ9HgwAQy8wsAlnSffSi2SHwd\nJR/QR2LRc4UlcQpAgPRHtJb2rvolhaUttfDrTU3g9lQOfb7i5ZO4g7a/Rs1Dzbtv\nAnv5I+CBmRMUp2bSrP9ceFUCAwEAAQ==\n-----END PUBLIC KEY-----\n'


class DiagnosticSession(requests.Session):
    def request(self, method, url, **kwargs):
        path = urlparse(url).path
        if path.endswith('/sendNow'):
            raise ValueError('Diagnostic stopped before sendNow; draft only.')
        response = super().request(method, url, **kwargs)
        print(f'{method} {path}: HTTP {response.status_code}')
        if method == 'POST' and path == '/v3/emailCampaigns' and response.status_code == 201:
            campaign_id = response.json()['id']
            report = super().request('GET', url + '/' + str(campaign_id),
                                     headers=kwargs['headers'], timeout=30)
            html = report.json().get('htmlContent', '')
            marker = 'name="briefberlin-cutoff"'
            print('watermark_round_trip=' + str(marker in html))
        if response.status_code >= 400:
            Path('diagnostic').mkdir(exist_ok=True)
            Path('diagnostic/public.pem').write_text(PUBLIC_KEY)
            encrypted = subprocess.run(
                ['openssl', 'pkeyutl', '-encrypt', '-pubin',
                 '-inkey', 'diagnostic/public.pem',
                 '-pkeyopt', 'rsa_padding_mode:oaep',
                 '-pkeyopt', 'rsa_oaep_md:sha256'],
                input=response.content[:400], capture_output=True, check=True,
            ).stdout
            Path('diagnostic/api-error.enc').write_bytes(encrypted)
        return response


newsletter_campaign.requests.Session = DiagnosticSession
raise SystemExit(newsletter_campaign.main(['--target', 'test']))
