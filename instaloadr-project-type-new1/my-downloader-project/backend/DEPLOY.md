DEPLOY — simple steps (Hinglish)

Yeh chhota guide backend ko server par chalane ke liye. Bilkul simple bhasha mein.

1) Repo update karo (server pe)
- Agar repo already server par hai toh pull karo:
  cd /root/instaloadr/instaloadr-project-type-new1/my-downloader-project
  git pull

2) Backend folder me jao aur script executable banao (sirf ek baar):
  cd backend
  chmod +x deploy_backend.sh

3) Script run karo (recommended) — yeh sab automatic karega:
  sudo ./deploy_backend.sh

  Script kya karega:
  - virtualenv (venv) banayega agar nahi hai
  - requirements.txt se Python packages install karega
  - /etc/systemd/system/instaloadr-backend.service file likhega (runs as root by default)
  - systemd ko reload karke service enable + start karega

4) Agar tum manual karna chahte ho (ek-ek):
  cd backend
  python3 -m venv venv
  source venv/bin/activate
  pip install --upgrade pip setuptools wheel
  pip install -r requirements.txt

  # create systemd service (example):
  sudo tee /etc/systemd/system/instaloadr-backend.service > /dev/null <<'EOF'
  [Unit]
  Description=InstaLoadr backend
  After=network.target

  [Service]
  User=root
  WorkingDirectory=/root/instaloadr/instaloadr-project-type-new1/my-downloader-project/backend
  Environment="ENVIRONMENT=production"
  Environment="CORS_ALLOWED_ORIGINS=https://instaloadr.com,https://www.instaloadr.com"
  ExecStart=/root/instaloadr/instaloadr-project-type-new1/my-downloader-project/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 5000
  Restart=on-failure
  RestartSec=5s

  [Install]
  WantedBy=multi-user.target
  EOF

  sudo systemctl daemon-reload
  sudo systemctl enable --now instaloadr-backend
  sudo systemctl status instaloadr-backend --no-pager

5) Check logs if service fail kare:
  sudo journalctl -u instaloadr-backend -n 200 --no-pager

6) HTTPS / SSL (Let's Encrypt)
- DNS root (instaloadr.com) and www and api must point to server IP.
- Make sure Cloudflare (agar use kar rahe ho) records are set to DNS-only (grey) while you run certbot.
- Then on server run:
  sudo certbot --nginx -d instaloadr.com -d www.instaloadr.com

7) After certbot success, test:
  curl -I https://instaloadr.com/health

Notes:
- This script and service run the app as root for simplicity. For production, move project to /opt/instaloadr and run service as a non-root user (www-data). Agar chaho, main iska exact one-line commands bhi provide kar dunga.
- Agar koi error aaye to "sudo journalctl -u instaloadr-backend -n 200 --no-pager" ka output yahan paste karo. Main fix bata dunga.

