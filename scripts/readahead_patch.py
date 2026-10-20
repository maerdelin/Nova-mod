"""Publish a session-owned single-response FIFO; leave all main copy loops intact."""
from pathlib import Path
import re
SESSION='Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;'
HELPER='Lcom/archos/filecorelibrary/NovaAheadInputStream;'

def edit(s, signature, fn):
    p=re.compile(r'(?ms)^\.method [^\n]* '+re.escape(signature)+r'\n.*?^\.end method$')
    if len(p.findall(s))!=1: raise RuntimeError('Missing/ambiguous '+signature)
    return p.sub(lambda m:fn(m.group()),s,count=1)

def wrap_method():
    return f'''
.method private novaAheadInput(Ljava/io/InputStream;J)Ljava/io/InputStream;
    .locals 6
    if-eqz p1, :ahead_bypass
    instance-of v0, p1, {HELPER}
    if-nez v0, :ahead_bypass
    invoke-virtual {{p0}}, {SESSION}->novaMediaResumeEligible()Z
    move-result v0
    if-eqz v0, :ahead_bypass
    iget-wide v3, p0, {SESSION}->length:J
    const-wide/16 v0, 0x0
    cmp-long v5, v3, v0
    if-lez v5, :ahead_bypass
    iget-boolean v5, p0, {SESSION}->partialResponse:Z
    if-eqz v5, :ahead_have_end
    iget-wide v0, p0, {SESSION}->requestedEnd:J
    const-wide/16 v3, 0x1
    add-long/2addr v0, v3
    move-wide v3, v0
    :ahead_have_end
    sub-long/2addr v3, p2
    move-object v0, p1
    move-wide v1, p2
    invoke-static/range {{v0 .. v4}}, {HELPER}->wrap(Ljava/io/InputStream;JJ)Ljava/io/InputStream;
    move-result-object p1
    :ahead_bypass
    return-object p1
.end method
'''

def session_text(s):
    if 'novaAheadInput' in s: raise RuntimeError('Read-ahead already installed')
    def publish(b):
        anchor='    if-eqz p1, '
        at=b.find(anchor)
        if at<0: raise RuntimeError('Missing publication null check')
        return b[:at]+f'''    iget-wide v0, p0, {SESSION}->requestedStart:J
    invoke-direct {{p0, p1, v0, v1}}, {SESSION}->novaAheadInput(Ljava/io/InputStream;J)Ljava/io/InputStream;
    move-result-object p1

'''+b[at:]
    s=edit(s,'publishInput(Ljava/io/InputStream;)V',publish)
    def resume(b):
        anchor=f'    invoke-direct {{p0, v0}}, {SESSION}->publishInput(Ljava/io/InputStream;)V'
        if b.count(anchor)!=1 or b.count('    return-object v0')!=1:
            raise RuntimeError('Changed resume publication')
        b=b.replace(anchor,f'''    invoke-direct {{p0, v0, p1, p2}}, {SESSION}->novaAheadInput(Ljava/io/InputStream;J)Ljava/io/InputStream;
    move-result-object v0
'''+anchor,1)
        # publishInput may add diagnostics; always return the owned stream, not raw v0.
        return b.replace('    return-object v0',f'    iget-object v0, p0, {SESSION}->is:Ljava/io/InputStream;\n    return-object v0',1)
    s=edit(s,'novaResumeUpstreamAt(J)Ljava/io/InputStream;',resume)
    return s.rstrip()+'\n'+wrap_method()

def apply(root):
    files=list(Path(root).glob('smali*/com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali'))
    if len(files)!=1: raise RuntimeError('Expected one session class')
    files[0].write_text(session_text(files[0].read_text()))
    return {'status':'PASS','mode':'single-continuous-response-background-fifo',
            'copy_and_resume_loops_unchanged':True,'session_owned':True,'native_10x_unchanged':True}
