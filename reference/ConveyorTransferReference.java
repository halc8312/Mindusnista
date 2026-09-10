/* SPDX-License-Identifier: GPL-3.0-only
 * Mindustry portions: Copyright (c) Anuken and contributors.
 * Modified/extracted test harness: 2026-09-10.
 * SOURCE: Anuken/Mindustry v159.7, commit
 * c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c,
 * core/src/mindustry/world/blocks/distribution/Conveyor.java:
 * onProximityUpdate, updateTile, pass, acceptItem, handleItem, add.
 *
 * This is a SOURCE-EXTRACTED, small conveyor reference, NOT a run of the
 * original engine. Arc/Building, rendering, teams, sleep/clog effects,
 * units, stack APIs, serialization and the entity scheduler are omitted.
 * Belts are size 1, on the same team, with delta = efficiency = timeScale = 1.
 * Each U record explicitly updates one belt. Cached minitem/mid and mutable
 * len are retained; the caller supplies initial minitem and mid starts at 0.
 * The initial fixtures are primed states, not constructor-only states.
 * lastInserted remains its upstream default 0 in these extracted methods.
 *
 * Development-only, JDK 17; not required by the Pythonista game.
 * stdin TSV: C name speed; B name x y rotation minitem count
 *            [item y x]...; U name; E. One JSON trace line per case.
 */
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

public class ConveyorTransferReference {
    static final float itemSpace = 0.4f;
    static final int capacity = 3;
    static final int[] dx = {1, 0, -1, 0}, dy = {0, 1, 0, -1};

    static float clamp(float value, float low, float high){
        return Math.max(low, Math.min(high, value));
    }

    static float approach(float value, float target, float amount){
        return value + clamp(target - value, -amount, amount);
    }

    static final class Belt {
        final String name;
        final int x, y, rotation;
        final String[] ids = new String[capacity];
        final float[] xs = new float[capacity], ys = new float[capacity];
        int len, mid, lastInserted;
        float minitem;
        Belt next;
        boolean aligned;

        Belt(String[] fields){
            name = identifier(fields[1]);
            x = Integer.parseInt(fields[2]);
            y = Integer.parseInt(fields[3]);
            rotation = Integer.parseInt(fields[4]);
            minitem = Float.parseFloat(fields[5]);
            len = Integer.parseInt(fields[6]);
            if(rotation < 0 || rotation > 3 || len < 0 || len > capacity ||
                    fields.length != 7 + 3 * len){
                throw new IllegalArgumentException("invalid belt record");
            }
            for(int i = 0; i < len; i++){
                ids[i] = identifier(fields[7 + i * 3]);
                ys[i] = Float.parseFloat(fields[8 + i * 3]);
                xs[i] = Float.parseFloat(fields[9 + i * 3]);
            }
        }

        // Edges.getFacingEdge/Tile.relativeTo replacement for size-1 neighbors.
        int incoming(Belt source){
            for(int d = 0; d < 4; d++){
                if(source.x + dx[d] == x && source.y + dy[d] == y) return d;
            }
            return -1;
        }

        boolean acceptItem(Belt source, String item){
            if(len >= capacity) return false;
            int incoming = incoming(source);
            if(incoming < 0) return false;
            int direction = Math.abs(incoming - rotation);
            return (((direction == 0) && minitem >= itemSpace) ||
                    ((direction % 2 == 1) && minitem > 0.7f)) && next != source;
        }

        void add(int offset){
            for(int i = Math.max(offset + 1, len); i > offset; i--){
                ids[i] = ids[i - 1];
                xs[i] = xs[i - 1];
                ys[i] = ys[i - 1];
            }
            len++;
        }

        void handleItem(Belt source, String item){
            if(len >= capacity) return;
            int incoming = incoming(source);
            int ang = incoming - rotation;
            float x = (ang == -1 || ang == 3) ? 1 : (ang == 1 || ang == -3) ? -1 : 0;
            if(Math.abs(incoming - rotation) == 0){
                add(0);
                xs[0] = x;
                ys[0] = 0;
                ids[0] = item;
            }else{
                add(mid);
                xs[mid] = x;
                ys[mid] = 0.5f;
                ids[mid] = item;
            }
        }

        boolean pass(String item){
            if(item != null && next != null && next.acceptItem(this, item)){
                next.handleItem(this, item);
                return true;
            }
            return false;
        }

        void updateTile(float speed){
            minitem = 1f;
            mid = 0;
            if(len == 0) return;
            float nextMax = aligned ? 1f - Math.max(itemSpace - next.minitem, 0) : 1f;
            float moved = speed;
            for(int i = len - 1; i >= 0; i--){
                float nextpos = (i == len - 1 ? 100f : ys[i + 1]) - itemSpace;
                float maxmove = clamp(nextpos - ys[i], 0, moved);
                ys[i] += maxmove;
                if(ys[i] > nextMax) ys[i] = nextMax;
                if(ys[i] > 0.5 && i > 0) mid = i - 1;
                xs[i] = approach(xs[i], 0, moved * 2);
                if(ys[i] >= 1f && pass(ids[i])){
                    if(aligned) next.xs[next.lastInserted] = xs[i];
                    // Upstream items.remove(ids[i], len-i) is represented by
                    // truncating the live prefix. No separate ItemModule here.
                    len = Math.min(i, len);
                }else if(ys[i] < minitem){
                    minitem = ys[i];
                }
            }
        }

        void appendJson(StringBuilder out){
            out.append("{\"count\":").append(len).append(",\"items\":[");
            for(int i = 0; i < len; i++){
                if(i != 0) out.append(',');
                out.append("{\"item\":\"").append(ids[i]).append("\",\"y\":")
                   .append(ys[i]).append(",\"x\":").append(xs[i]).append('}');
            }
            out.append("],\"cache\":{\"minitem\":").append(minitem)
               .append(",\"mid\":").append(mid)
               .append(",\"lastInserted\":").append(lastInserted).append("}}");
        }
    }

    static String identifier(String value){
        if(!value.matches("[A-Za-z][A-Za-z0-9_]*")){
            throw new IllegalArgumentException("invalid identifier");
        }
        return value;
    }

    static void connect(Map<String, Belt> belts){
        for(Belt belt : belts.values()){
            belt.next = null;
            for(Belt other : belts.values()){
                if(other.x == belt.x + dx[belt.rotation] &&
                        other.y == belt.y + dy[belt.rotation]) belt.next = other;
            }
            belt.aligned = belt.next != null && belt.rotation == belt.next.rotation;
        }
    }

    public static void main(String[] args) throws Exception {
        Map<String, Belt> belts = new LinkedHashMap<>();
        BufferedReader reader = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String name = null;
        float speed = 0;
        int updates = 0;
        StringBuilder trace = null;
        for(String line; (line = reader.readLine()) != null; ){
            String[] fields = line.split("\t", -1);
            switch(fields[0]){
                case "C":
                    if(name != null || fields.length != 3) throw new IllegalArgumentException("invalid case start");
                    name = identifier(fields[1]);
                    speed = Float.parseFloat(fields[2]);
                    belts.clear();
                    updates = 0;
                    trace = new StringBuilder("{\"name\":\"").append(name).append("\",\"frames\":[");
                    break;
                case "B":
                    if(name == null || updates != 0) throw new IllegalArgumentException("belt outside setup");
                    Belt belt = new Belt(fields);
                    if(belts.putIfAbsent(belt.name, belt) != null) throw new IllegalArgumentException("duplicate belt");
                    break;
                case "U":
                    if(name == null || fields.length != 2 || !belts.containsKey(fields[1])){
                        throw new IllegalArgumentException("invalid update");
                    }
                    if(updates == 0) connect(belts);
                    belts.get(fields[1]).updateTile(speed);
                    if(updates++ != 0) trace.append(',');
                    trace.append("{\"update\":\"").append(fields[1]).append("\",\"belts\":{");
                    boolean first = true;
                    for(Belt current : belts.values()){
                        if(!first) trace.append(',');
                        first = false;
                        trace.append('"').append(current.name).append("\":");
                        current.appendJson(trace);
                    }
                    trace.append("}}");
                    break;
                case "E":
                    if(name == null || fields.length != 1 || updates == 0){
                        throw new IllegalArgumentException("invalid case end");
                    }
                    System.out.println(trace.append("]}"));
                    name = null;
                    break;
                default:
                    throw new IllegalArgumentException("unknown protocol record");
            }
        }
        if(name != null) throw new IllegalArgumentException("unterminated case");
    }
}
