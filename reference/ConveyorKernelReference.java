/* SPDX-License-Identifier: GPL-3.0-only
 * Mindustry portions: Copyright (c) Anuken and contributors.
 * Modified/extracted test harness: 2026-09-09.
 * SOURCE: Anuken/Mindustry tag v159.7,
 * core/src/mindustry/world/blocks/distribution/Conveyor.java lines 239-249,320-325
 * core/src/mindustry/world/blocks/production/Drill.java lines 154-155,273-293
 *
 * This is an ISOLATED arithmetic reference, NOT the full original engine.
 * Arc/Building/world dependencies, transfer, effects and sleep are omitted.
 * It intentionally uses Java float, as the upstream does.
 * Run: javac ConveyorKernelReference.java && java ConveyorKernelReference
 */
import java.util.Arrays;
import java.util.Locale;
import java.util.Random;

public class ConveyorKernelReference {
    static final float itemSpace = 0.4f;
    static float clamp(float x, float low, float high){
        return Math.max(low, Math.min(high, x));
    }
    static float approach(float x, float target, float delta){
        return x + clamp(target-x, -delta, delta);
    }
    static void movement(float[] ys, float[] xs, float speed, float nextMinimum, boolean aligned){
        float nextMax = aligned ? 1f - Math.max(itemSpace - nextMinimum, 0) : 1f;
        float moved = speed;
        for(int i = ys.length - 1; i >= 0; i--){
            float nextpos = (i == ys.length - 1 ? 100f : ys[i + 1]) - itemSpace;
            float maxmove = clamp(nextpos - ys[i], 0, moved);
            ys[i] += maxmove;
            if(ys[i] > nextMax) ys[i] = nextMax;
            xs[i] = approach(xs[i], 0, moved*2);
        }
    }
    static boolean accepts(float minitem, int len, int incoming, int rotation,
                           boolean rotates, boolean front){
        if(len >= 3) return false;
        int direction = Math.abs(incoming-rotation);
        return (((direction == 0) && minitem >= itemSpace) ||
                ((direction % 2 == 1) && minitem > 0.7f)) && !(rotates && front);
    }
    public static void main(String[] args){
        Locale.setDefault(Locale.ROOT);
        Random random = new Random(1597);
        System.out.println("{\"reference_kind\":\"isolated Java float kernels; not a full Mindustry run\",\"movement\":[");
        for(int k=0; k<120; k++){
            int len=k%4;
            float[] ys=new float[len], xs=new float[len];
            for(int i=0; i<len; i++){
                ys[i]=i*0.4f+random.nextFloat()*0.08f;
                xs[i]=random.nextFloat()*2-1;
            }
            String initialY=Arrays.toString(ys), initialX=Arrays.toString(xs);
            float speed=new float[]{0.046f,0.0801f,0.2f}[k%3];
            float nextMin=new float[]{0f,0.1f,0.4f,0.75f,1f}[k%5];
            boolean aligned=(k%2 == 0);
            int steps=new int[]{0,1,2,5,20,60,120}[k%7];
            for(int t=0; t<steps; t++) movement(ys,xs,speed,nextMin,aligned);
            System.out.printf("%s{\"ys\":%s,\"xs\":%s,\"speed\":%s,\"next_minimum\":%s,\"aligned\":%s,\"steps\":%d,\"expected_y\":%s,\"expected_x\":%s}%n",
                k==0?"":",", initialY,initialX,speed,nextMin,aligned,steps,Arrays.toString(ys),Arrays.toString(xs));
        }
        System.out.println("],\"acceptance\":[");
        boolean first=true;
        for(float min: new float[]{0f,.399f,.4f,.4001f,.7f,.7001f,1f})
        for(int count: new int[]{0,2,3})
        for(int incoming=0; incoming<4; incoming++)
        for(int rotation=0; rotation<4; rotation++)
        for(int flags=0; flags<4; flags++){
            boolean rotates=(flags&1)!=0, front=(flags&2)!=0;
            System.out.printf("%s{\"minimum\":%s,\"count\":%d,\"incoming\":%d,\"rotation\":%d,\"rotates\":%s,\"front\":%s,\"expected\":%s}%n",
                first?"":",",min,count,incoming,rotation,rotates,front,
                accepts(min,count,incoming,rotation,rotates,front));
            first=false;
        }
        System.out.println("],\"dry_drill\":[");
        first=true;
        for(int count=1; count<=4; count++)
        for(int steps: new int[]{0,1,30,66,67,162,196,300,600,1200}){
            float progress=0f, warmup=0f;
            int produced=0;
            for(int t=0; t<steps; t++){
                float delay=600f+50f*1;
                float speed=1f;
                warmup=approach(warmup,speed,.015f);
                progress+=count*speed*warmup;
                if(progress>=delay){
                    produced+=(int)(progress/delay);
                    progress%=delay;
                }
            }
            System.out.printf("%s{\"count\":%d,\"steps\":%d,\"progress\":%s,\"warmup\":%s,\"produced\":%d}%n",
                first?"":",",count,steps,progress,warmup,produced);
            first=false;
        }
        System.out.println("]}");
    }
}
