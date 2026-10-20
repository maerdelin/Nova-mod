package com.archos.filecorelibrary;
import java.io.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.BooleanSupplier;

public final class AheadHarness {
    static final int M=1024*1024;
    static void check(boolean b,String m){if(!b)throw new AssertionError(m);}
    static void until(BooleanSupplier p)throws Exception{
        long end=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);
        while(!p.getAsBoolean()&&System.nanoTime()<end)Thread.sleep(2);
        check(p.getAsBoolean(),"deadline");
    }
    static final class Source extends InputStream {
        final long start,total,failAt;final int maxRead;
        volatile long pos;volatile boolean closed;final AtomicInteger closing=new AtomicInteger(),active=new AtomicInteger(),peak=new AtomicInteger();
        volatile String reader;
        Source(long start,long total,int maxRead,long failAt){this.start=start;this.total=total;this.maxRead=maxRead;this.failAt=failAt;}
        public int read(){throw new AssertionError("single-byte upstream read");}
        public int read(byte[] b,int off,int n)throws IOException{
            check(!closed,"read after close");int a=active.incrementAndGet();peak.accumulateAndGet(a,Math::max);
            try{
                reader=Thread.currentThread().getName();
                if(pos==failAt)throw new IOException("injected-read-fault");
                if(pos>=total)return -1;
                n=(int)Math.min(Math.min(n,maxRead),total-pos);
                if(failAt>=0)n=(int)Math.min(n,failAt-pos);
                for(int i=0;i<n;i++)b[off+i]=(byte)((start+pos+i)%251);
                pos+=n;return n;
            }finally{active.decrementAndGet();}
        }
        public void close(){closed=true;closing.incrementAndGet();}
    }
    static NovaAheadInputStream ahead(Source s,long expected){
        InputStream in=NovaAheadInputStream.wrap(s,s.start,expected);
        check(in instanceof NovaAheadInputStream,"not wrapped");return(NovaAheadInputStream)in;
    }
    static long drain(InputStream in,long start,long expected,boolean fail)throws Exception{
        byte[] b=new byte[177013];long pos=0;
        try{
            for(;;){int n=in.read(b);if(n<0)break;for(int i=0;i<n;i++)check((b[i]&255)==(start+pos+i)%251,"bytes "+(pos+i));pos+=n;}
            check(!fail,"fault swallowed");
        }catch(IOException e){check(fail,"unexpected fault "+e);}
        check(pos==expected,"length "+pos+" != "+expected);return pos;
    }
    static void run(String mode)throws Exception{
        if(mode.equals("pause")){
            Source s=new Source(4294979641L,40L*M+37,4093,-1);NovaAheadInputStream p=ahead(s,s.total);
            until(()->p.receivedBytes()==p.capacityBytes());long initial=p.receivedBytes();
            check(initial==16L*M&&p.deliveredBytes()==0,"did not prefetch independently");
            Thread.sleep(80);check(p.receivedBytes()==initial,"capacity exceeded");
            byte[] b=new byte[M];int n=p.read(b);check(n==M,"release");
            for(int i=0;i<n;i++)check((b[i]&255)==(s.start+i)%251,"prefix");
            until(()->p.receivedBytes()==initial+M);
            check(p.available()==p.capacityBytes(),"did not refill");
            drain(p,s.start+M,s.total-M,false);p.close();until(p::producerDone);
            check(s.peak.get()==1&&s.closing.get()==1&&s.reader.startsWith("Nova-Ahead-"),"not one owned reader");
            System.out.println("PASS pause: consumer=0 prefetch="+initial+" cap; consumption resumes producer; exact40MiB+37; one source reader");
        }else if(mode.equals("failure")||mode.equals("early")){
            long prefix=2L*M+333;Source s=new Source(3000000000L,mode.equals("early")?prefix:8L*M,7777,mode.equals("failure")?prefix:-1);
            NovaAheadInputStream p=ahead(s,8L*M);until(p::producerDone);
            drain(p,s.start,prefix,true);p.close();check(s.closing.get()==1,"source closed twice");
            System.out.println("PASS "+mode+": queued prefix drains before original error; response closed before retry");
        }else if(mode.equals("cancel-full")){
            for(int i=0;i<16;i++){
                Source s=new Source(i,32L*M,65536,-1);NovaAheadInputStream p=ahead(s,s.total);
                until(()->p.receivedBytes()==p.capacityBytes());p.close();p.close();until(p::producerDone);
                check(s.closing.get()==1,"close count");try{p.read();throw new AssertionError("read closed");}catch(IOException good){}
            }
            System.out.println("PASS 16 cancellation/seek cycles at full FIFO; worker exits and admission memory reclaimed");
        }else if(mode.equals("cancel-wait")){
            for(int i=0;i<16;i++){
                CountDownLatch entered=new CountDownLatch(1),released=new CountDownLatch(1);AtomicInteger closes=new AtomicInteger();
                InputStream s=new InputStream(){public int read(){return -1;}public int read(byte[] b,int o,int n)throws IOException{
                    entered.countDown();try{released.await();}catch(InterruptedException e){Thread.currentThread().interrupt();}throw new IOException("closed");}
                    public void close(){closes.incrementAndGet();released.countDown();}};
                NovaAheadInputStream p=(NovaAheadInputStream)NovaAheadInputStream.wrap(s,0,32L*M);
                entered.await(1,TimeUnit.SECONDS);AtomicReference<Throwable> error=new AtomicReference<>();
                Thread consumer=new Thread(()->{try{p.read();}catch(Throwable e){error.set(e);}});consumer.start();
                p.close();consumer.join(1000);until(p::producerDone);
                check(!consumer.isAlive()&&error.get() instanceof IOException&&closes.get()==1,"blocked cancellation");
            }
            System.out.println("PASS 16 cancellation cycles with blocked source and blocked consumer; both unblock");
        }else if(mode.equals("extent")){
            Source s=new Source(1L<<33,10L*M,113,-1);NovaAheadInputStream p=ahead(s,M+27);
            drain(p,s.start,M+27,false);until(p::producerDone);
            check(s.pos==M+27,"overread requested range");p.close();
            check(NovaAheadInputStream.wrap(new ByteArrayInputStream(new byte[2]),0,2) instanceof ByteArrayInputStream,"tiny request unexpectedly buffered");
            System.out.println("PASS declared extent, nonaligned shorts, 64bit offset, zero extra bytes; small metadata bypass");
        }else if(mode.equals("budget")){
            Source a=new Source(0,32L*M,65536,-1),b=new Source(0,32L*M,65536,-1),c=new Source(0,32L*M,65536,-1);
            NovaAheadInputStream x=ahead(a,a.total),y=ahead(b,b.total);
            InputStream z=NovaAheadInputStream.wrap(c,0,c.total);check(z==c,"process FIFO budget exceeded");
            x.close();y.close();until(x::producerDone);until(y::producerDone);
            NovaAheadInputStream q=ahead(c,c.total);q.close();until(q::producerDone);
            System.out.println("PASS process admission cap32MiB, graceful continuous-single fallback, reuse after release");
        }else if(mode.equals("validation")){
            Source s=new Source(0,M,101,-1);NovaAheadInputStream p=ahead(s,M);
            try{p.read(null,0,0);throw new AssertionError();}catch(NullPointerException good){}
            try{p.read(new byte[3],2,2);throw new AssertionError();}catch(IndexOutOfBoundsException good){}
            check(p.read(new byte[0],0,0)==0,"zero read");check(!p.markSupported(),"unexpected seek semantics");
            p.close();until(p::producerDone);System.out.println("PASS read contract and no invented mark/reset");
        }else throw new AssertionError(mode);
    }
    public static void main(String[] args)throws Exception{run(args[0]);}
}
