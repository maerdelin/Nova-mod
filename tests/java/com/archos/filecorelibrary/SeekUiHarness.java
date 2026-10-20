package com.archos.filecorelibrary;
import java.util.*;
/** Deterministic virtual-clock checks of the production UI-only timer. */
public final class SeekUiHarness {
    static void check(boolean value,String why){if(!value)throw new AssertionError(why);}
    static final class Clock implements NovaControlbarAutoHide.Scheduler {
        long now; final Map<Runnable,Long> tasks=new LinkedHashMap<Runnable,Long>();int peak;
        public long now(){return now;}
        public void remove(Runnable task){tasks.remove(task);}
        public void post(Runnable task,long ms){check(ms>=0,"negative delay");check(!tasks.containsKey(task),"duplicate callback");tasks.put(task,now+ms);peak=Math.max(peak,tasks.size());}
        void until(long goal){int steps=0;for(;;){Runnable selected=null;long next=Long.MAX_VALUE;for(Map.Entry<Runnable,Long> e:tasks.entrySet())if(e.getValue()<next){next=e.getValue();selected=e.getKey();}if(selected==null||next>goal)break;check(++steps<100000,"timer spins");now=next;tasks.remove(selected);selected.run();}now=goal;}
    }
    static final class Host implements NovaControlbarAutoHide.Host {
        boolean active=true,playing=true,held,dragged,menu;int hides;
        public boolean novaHideActive(){return active;}
        public boolean novaHideReady(boolean allowPaused){return !held&&!dragged&&!menu&&(playing||allowPaused);}
        public void novaHideControls(){hides++;active=false;}
    }
    public static void main(String[] args){
        String name=args[0];Host h=new Host();Clock c=new Clock();NovaControlbarAutoHide timer=new NovaControlbarAutoHide(h,c);
        if(name.equals("steady")){timer.arm(3000);c.until(2999);check(h.hides==0,"early hide");c.until(3000);check(h.hides==1,"missing hide");}
        else if(name.equals("delayed")){h.playing=false;timer.arm(3000);c.until(30000);check(h.hides==0,"hidden while paused");h.playing=true;c.until(33249);check(h.hides==0,"deadline did not start at readiness");c.until(33250);check(h.hides==1,"lost timer after playing becomes true");}
        else if(name.equals("holding")){h.held=true;timer.arm(3000);c.until(12000);check(h.hides==0,"hidden while held");h.held=false;timer.arm(3000);c.until(14999);check(h.hides==0,"early release hide");c.until(15000);check(h.hides==1,"release did not rearm");}
        else if(name.equals("dragging")){h.dragged=true;timer.arm(3000);c.until(10000);h.dragged=false;c.until(13250);check(h.hides==1,"drag end lost hide");}
        else if(name.equals("paused")){timer.arm(3000);c.until(2000);h.playing=false;c.until(30000);check(h.hides==0,"manual pause hidden");h.playing=true;c.until(33250);check(h.hides==1,"manual resume not observed");}
        else if(name.equals("menu")){timer.arm(3000);c.until(2000);h.menu=true;c.until(10000);check(h.hides==0,"menu hidden");h.menu=false;c.until(13250);check(h.hides==1,"menu close lost hide");}
        else if(name.equals("rearm")){timer.arm(3000);c.until(2500);timer.arm(3000);c.until(5499);check(h.hides==0,"old deadline survived new input");c.until(5500);check(h.hides==1,"rearm deadline missing");}
        else if(name.equals("cancel")){timer.arm(3000);c.until(1000);timer.cancel();timer.run();c.until(10000);check(h.hides==0&&c.tasks.isEmpty(),"cancel left live callback");}
        else if(name.equals("stop")){timer.arm(3000);c.until(500);h.active=false;c.until(10000);check(h.hides==0&&c.tasks.isEmpty(),"inactive owner retained");}
        else if(name.equals("explicit")){h.playing=false;timer.arm(5000);c.until(4999);check(h.hides==0,"early explicit pause hide");c.until(5000);check(h.hides==1,"5s pause policy lost");}
        else if(name.equals("bounded")){for(int i=0;i<10000;i++)timer.arm(3000);check(c.tasks.size()==1&&c.peak==1,"unbounded callback queue");c.until(3000);check(h.hides==1,"polling resets deadline");}
        else if(name.equals("owners")){Host h2=new Host();NovaControlbarAutoHide second=new NovaControlbarAutoHide(h2,c);timer.arm(3000);second.arm(3000);timer.cancel();c.until(3000);check(h.hides==0&&h2.hides==1,"cross-owner cancellation");}
        else if(name.equals("zero")){timer.arm(3000);timer.arm(0);c.until(10000);check(h.hides==0&&c.tasks.isEmpty(),"zero timeout not persistent");}
        else throw new AssertionError(name);
        check(c.tasks.isEmpty(),"completed timer retains callbacks");
        System.out.println("PASS UI "+name+" hides="+h.hides+" playbackMutations=0");
    }
}
