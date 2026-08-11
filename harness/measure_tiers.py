import subprocess, tiktoken, os
enc = tiktoken.get_encoding("cl100k_base")
ov = os.path.expanduser("~/openviking-lab/.venv/bin/ov")
docs = {"prd-checkout":"team-alpha","design-review-auth":"team-alpha",
        "postmortem-latency":"team-beta","conventions":"team-beta"}
print(f"{'document':<22}{'L2 orig':>9}{'L0':>7}{'L1':>7}{'L0+L1 vs L2':>13}")
tot=[0,0,0]
for d,t in docs.items():
    u=f"viking://resources/corpus/{t}/{d}"
    raw=open(os.path.expanduser(f"~/openviking-lab/corpus/{t}/{d}.md")).read()
    def run(c):
        r=subprocess.run([ov,c,u],capture_output=True,text=True,timeout=120)
        return r.stdout.strip()
    l0,l1=run("abstract"),run("overview")
    a,b,c=len(enc.encode(raw)),len(enc.encode(l0)),len(enc.encode(l1))
    tot[0]+=a;tot[1]+=b;tot[2]+=c
    print(f"{d:<22}{a:>9}{b:>7}{c:>7}{(b+c)/a:>12.1f}x")
print(f"{'TOTAL':<22}{tot[0]:>9}{tot[1]:>7}{tot[2]:>7}{(tot[1]+tot[2])/tot[0]:>12.1f}x")
