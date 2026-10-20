package nova.test;
import java.lang.reflect.*;
import java.util.*;
/** Uses the actual final APK controller and timer with deterministic injected time.
 * No UI constructor, playback side effects, test code or fake media shipped in APK. */
public final class SeekUiApkProbe {
    static void check(boolean v,String why){if(!v)throw new AssertionError(why);}
    static Class<?> pc,player,policy,host,scheduler;static Object controller,p;
    static boolean playing;static int mutations,hides;static long now;
    static final Map<Runnable,Long> tasks=new LinkedHashMap<Runnable,Long>();
    static void field(Object o,Class<?> c,String n,Object v)throws Exception{Field f=c.getDeclaredField(n);f.setAccessible(true);f.set(o,v);}
    static Object allocate(Class<?> c)throws Exception{Class<?> u=Class.forName("sun.misc.Unsafe");Object a=null;for(Field f:u.getDeclaredFields())if(f.getType()==u&&Modifier.isStatic(f.getModifiers())){f.setAccessible(true);a=f.get(null);if(a!=null)break;}return u.getMethod("allocateInstance",Class.class).invoke(a,c);}
    static void tick(long goal){for(int guard=0;;guard++){check(guard<100000,"timer spin");Runnable task=null;long when=Long.MAX_VALUE;for(Map.Entry<Runnable,Long> e:tasks.entrySet())if(e.getValue()<when){when=e.getValue();task=e.getKey();}if(task==null||when>goal)break;now=when;tasks.remove(task);task.run();}now=goal;}
    static Object zero(Class<?> c){if(c==boolean.class)return false;if(c==int.class)return 0;if(c==long.class)return 0L;if(c==float.class)return 0f;if(c==double.class)return 0d;return null;}
    static void invoke(String name,Class<?>[] types,Object... args)throws Exception{Method m=pc.getDeclaredMethod(name,types);m.setAccessible(true);m.invoke(controller,args);}
    public static void main(String[] args)throws Exception{
        pc=Class.forName("com.archos.mediacenter.video.player.PlayerController");player=Class.forName("com.archos.mediacenter.video.player.Player");
        policy=Class.forName("com.archos.filecorelibrary.NovaControlbarAutoHide");host=Class.forName(policy.getName()+"$Host");scheduler=Class.forName(policy.getName()+"$Scheduler");
        check(host.isAssignableFrom(pc),"controller Host hook absent");controller=allocate(pc);p=allocate(player);
        Class<?> media=Class.forName("com.archos.medialib.IMediaPlayer");
        Object m=Proxy.newProxyInstance(media.getClassLoader(),new Class<?>[]{media},(o,method,a)->{String n=method.getName();if(n.equals("isPlaying"))return playing;if(n.equals("start")||n.equals("pause")||n.startsWith("seek")){mutations++;throw new AssertionError("UI test mutated playback: "+n);}return zero(method.getReturnType());});
        field(p,player,"mMediaPlayer",m);field(p,player,"mCurrentState",3);field(null,player,"sPlayer",p);
        field(controller,pc,"mIsStopped",false);field(null,pc,"mControlBarShowing",true);
        Object delegate=Proxy.newProxyInstance(host.getClassLoader(),new Class<?>[]{host},(o,method,a)->{if(method.getName().equals("novaHideControls")){hides++;return null;}return pc.getMethod(method.getName(),method.getParameterTypes()).invoke(controller,a);});
        Object clock=Proxy.newProxyInstance(scheduler.getClassLoader(),new Class<?>[]{scheduler},(o,method,a)->{switch(method.getName()){case "now":return now;case "remove":tasks.remove((Runnable)a[0]);return null;case "post":check(!tasks.containsKey(a[0]),"duplicate timer");tasks.put((Runnable)a[0],now+(Long)a[1]);return null;default:return null;}});
        Object timer=policy.getConstructor(host,scheduler).newInstance(delegate,clock);field(controller,pc,"mNovaAutoHide",timer);
        // Actual APK sendFadeOut hook must schedule even while not yet playing.
        field(controller,pc,"mDragging",true); // stale legacy seek flag must not veto actual idle
        playing=false;invoke("sendFadeOut",new Class<?>[]{int.class},3000);tick(10000);check(hides==0,"paused hidden");playing=true;tick(13249);check(hides==0,"early hide");tick(13250);check(hides==1,"playing transition lost timeout");
        // Actual key/drag guards. Neither completion flag nor busy flag is forged.
        field(controller,pc,"mNovaTouchTracking",true);invoke("novaSeekHideEvent",new Class<?>[]{});tick(18000);check(hides==1,"drag hidden");field(controller,pc,"mNovaTouchTracking",false);field(controller,pc,"mSeekKeyDirection",1);tick(22000);check(hides==1,"held key hidden");field(controller,pc,"mSeekKeyDirection",0);invoke("novaSeekHideEvent",new Class<?>[]{});tick(25000);check(hides==2,"release hook did not hide");
        field(controller,pc,"isTVMenuDisplayed",true);invoke("novaSeekHideEvent",new Class<?>[]{});tick(30000);check(hides==2,"menu hidden");field(controller,pc,"isTVMenuDisplayed",false);tick(33250);check(hides==3,"menu exit lost timer");
        invoke("novaSeekHideEvent",new Class<?>[]{});invoke("novaCancelHide",new Class<?>[]{});tick(40000);check(hides==3&&tasks.isEmpty(),"cancel pending");
        check(mutations==0,"playback mutated");
        // Constants must retain normal time steps; ISO native mode selects these.
        Field steps=pc.getDeclaredField("SEEK_ACCEL_MSECS");steps.setAccessible(true);check(Arrays.equals((int[])steps.get(null),new int[]{5000,15000,30000,60000}),"normal seek steps changed");
        System.out.println("SEEK_UI_FINAL_APK_PROBE=PASS latePlaying=1 heldRelease=1 menu=1 cancel=1 playbackMutations="+mutations+" hides="+hides);
    }
}
