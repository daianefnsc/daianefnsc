#!/data/data/com.termux/files/usr/bin/sh
# Liga o sistema de câmeras quando o tablet inicia (usado pelo app Termux:Boot).
termux-wake-lock
cd ~/daianefnsc/sistema-cameras || exit 1
# se cair, espera 10s e liga de novo
while true; do
  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> sistema.log 2>&1
  sleep 10
done
