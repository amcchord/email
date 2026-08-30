#!/usr/bin/env bash
set -euo pipefail

remote_host="${MAIL_REMOTE_HOST:-root@email.mcchord.net}"

ssh \
    -o BatchMode=yes \
    -o ConnectTimeout=12 \
    "$remote_host" \
    'set -u
     overall_status=0

     echo "== Host =="
     date --iso-8601=seconds
     hostname -f 2>/dev/null || hostname
     sed -n "s/^PRETTY_NAME=//p" /etc/os-release

     echo
     echo "== Git =="
     git -c safe.directory=/opt/mail -C /opt/mail status --short --branch
     git -c safe.directory=/opt/mail -C /opt/mail log -1 --oneline --decorate

     echo
     echo "== Services =="
     for unit in mailapp mailworker mailworker-cron mailtui caddy postgresql redis-server; do
       state="$(systemctl is-active "$unit" 2>/dev/null || true)"
       printf "%-24s %s\n" "$unit" "${state:-unknown}"
       if [ "$state" != "active" ]; then overall_status=1; fi
     done

     echo
     echo "== Public health =="
     if ! curl -fsS --max-time 10 https://email.mcchord.net/api/health; then
       overall_status=1
     fi
     echo

     echo
     echo "== Capacity =="
     df -h /opt/mail
     free -h

     exit "$overall_status"'
