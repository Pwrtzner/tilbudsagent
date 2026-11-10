#!/usr/bin/env bash
# Kører inde i emulatoren: installér APK, start appen, vent på Python-serveren og kald API'et.
set -u
APK="$1"
adb install -r "$APK" || { echo "Installation fejlede"; exit 1; }
adb logcat -c
adb shell am start -n dk.pwrtzner.tilbudsagent/.MainActivity
adb forward tcp:18765 tcp:18765

ok=0
for i in $(seq 1 90); do
  if curl -fs http://127.0.0.1:18765/api/ping | grep -q tilbudsagent; then ok=1; break; fi
  sleep 2
done

if [ "$ok" != 1 ]; then
  echo "Serveren svarede ikke på 3 minutter. Logcat:"
  adb logcat -d | grep -iE "python|tilbudsagent|chaquopy|AndroidRuntime|FATAL" | tail -80
  exit 1
fi

curl -fs http://127.0.0.1:18765/api/ping; echo
STATE=$(# forgrundstjenesten, der holder en hentning i live: start, og den skal lukke sig selv, når der ikke kører noget
adb logcat -c
adb shell am start-foreground-service -n dk.pwrtzner.tilbudsagent/.HentTjeneste
sleep 30
if adb shell dumpsys activity services dk.pwrtzner.tilbudsagent | grep -q "HentTjeneste"; then
  echo "Forgrundstjenesten lukkede ikke sig selv."; adb shell dumpsys activity services dk.pwrtzner.tilbudsagent | grep -A6 HentTjeneste | head -20; exit 1
fi
if adb logcat -d | grep -E "FATAL EXCEPTION|hent-tjeneste fejlede"; then echo "Forgrundstjenesten fejlede."; exit 1; fi
echo "OK: forgrundstjeneste startede og lukkede igen"
curl -fs http://127.0.0.1:18765/api/state) || { echo "/api/state fejlede"; exit 1; }
echo "$STATE" | python3 -c "
import json,sys
s=json.load(sys.stdin)
assert s['varer'], 'ingen startvarer'
assert s['cfg']['butikker'], 'ingen butikker'
print('OK: version', s['version'], '|', len(s['varer']), 'varer |', len(s['cfg']['butikker']), 'butikker | data:', s['data_mappe'])
"
curl -fs http://127.0.0.1:18765/ | grep -q "Tilbudsagent" || { echo "app.html mangler"; exit 1; }

# baggrundsjobbet (WorkManager kører Python i en Worker): start ét job og vent på dets logbesked
adb shell am force-stop dk.pwrtzner.tilbudsagent
sleep 2
adb logcat -c
adb shell am start -n dk.pwrtzner.tilbudsagent/.MainActivity --ez worker_test true
kort=0
for i in $(seq 1 60); do
  if adb logcat -d -s Tilbudsagent:I | grep -q "worker færdig"; then kort=1; break; fi
  sleep 5
done
if [ "$kort" != 1 ]; then
  echo "Baggrundsjobbet kørte ikke på 5 minutter. Logcat:"
  adb logcat -d | grep -iE "python|tilbudsagent|workmanager|AndroidRuntime|FATAL" | tail -80
  exit 1
fi
adb logcat -d -s Tilbudsagent:I | grep "worker færdig" | head -2
for i in $(seq 1 60); do curl -fs http://127.0.0.1:18765/api/ping | grep -q tilbudsagent && break; sleep 2; done
curl -fs http://127.0.0.1:18765/api/state | python3 -c "import json,sys; s=json.load(sys.stdin); assert 'nyt' in s['dash']; print('OK: feed i state')"

# kan appen hente fra internettet (Overpass/Tjek) med Androids certifikater? Kun logget, ikke krævet.
curl -fs -XPOST http://127.0.0.1:18765/api/geokod -H 'Content-Type: application/json' -d '{"q":"Rådhuspladsen 1, København"}' | head -c 300; echo

# appens egen WebView: er siden indlæst? (UI-trådens log)
sleep 3
adb logcat -d | grep -iE "Tilbudsagent" | tail -15
exit 0
