#!/bin/bash
# 頻寬測試：單一、限速、PID 固定的下載，方便在 asktop 觀察 per-process 流量。
# 用法：./bwtest.sh [每秒速率]
#   ./bwtest.sh          # 預設限速 5MB/s
#   ./bwtest.sh 10M      # 限速 10MB/s
#   ./bwtest.sh 0        # 不限速（全速）
#
# 為什麼這樣設計：只起「一隻」curl 抓一個真實大檔，限速下可持續數分鐘，PID 全程不變。
# asktop 以 PID 為 row key，PID 穩定才顯示得穩。用 exec 讓 curl 繼承本 script 的 PID，好找。

RATE="${1:-5M}"
if [ "$RATE" = "0" ]; then LIMIT=""; RATE_DESC="全速"; else LIMIT="--limit-rate $RATE"; RATE_DESC="$RATE/s"; fi

# 幾個有「真實大小」的公開測試檔（會依序嘗試，挑第一個連得到的）
MIRRORS=(
  "http://speedtest.tele2.net/1GB.zip"
  "https://proof.ovh.net/files/1Gb.dat"
  "http://ipv4.download.thinkbroadband.com/1GB.zip"
)

URL=""
for m in "${MIRRORS[@]}"; do
  if curl -sI --max-time 6 "$m" | head -1 | grep -q "200"; then URL="$m"; break; fi
done
if [ -z "$URL" ]; then
  echo "所有鏡像都連不到，請檢查對外網路（curl -I <網址> 手動測）"; exit 1
fi

echo "來源：$URL"
echo "速率：$RATE_DESC   (Ctrl-C 停止)"
echo ">>> 在 asktop 過濾 'curl'，或找 PID = $$（本 script，exec 後即為 curl 的 PID） <<<"
exec curl $LIMIT -o /dev/null "$URL"
