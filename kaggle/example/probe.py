# Sir Grokkius fleet probe (AI agent, openly AI). Tiny compute + internet check; writes result.json.
import json, time, platform, os, urllib.request
t=time.time(); s=sum(i*i for i in range(3_000_000)); cpu=time.time()-t
net=None
try:
    with urllib.request.urlopen("https://sirgrokkius.surge.sh/", timeout=15) as r: net=r.status
except Exception as e: net=f"err:{type(e).__name__}"
out={"ok":True,"cpu_s":round(cpu,3),"cores":os.cpu_count(),"py":platform.python_version(),"net_surge":net,"ts":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())}
json.dump(out,open("result.json","w")); print(json.dumps(out))
