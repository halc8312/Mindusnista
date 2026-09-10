/* SPDX-License-Identifier: GPL-3.0-only
 * Mindustry portions: Copyright (c) Anuken and contributors.
 * Source-extracted harness: 2026-09-10.
 * SOURCE: Anuken/Mindustry v159.7,
 * c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c:
 *   core/src/mindustry/entities/comp/BuildingComp.java: dump, offload,
 *     incrementDump, canDump, handleItem and default acceptItem;
 *   core/src/mindustry/world/blocks/production/Drill.java: dry updateTile;
 *   core/src/mindustry/world/blocks/distribution/Conveyor.java: updateTile,
 *     onProximityUpdate, pass, acceptItem, handleItem, add;
 *   core/src/mindustry/world/blocks/distribution/Router.java: updateTile,
 *     getTileTarget (uncontrolled branch), acceptItem and handleItem;
 *   core/src/mindustry/world/Edges.java: getFacingEdge;
 *   core/src/mindustry/world/Tile.java: relativeTo.
 *
 * This runs the extracted receiver methods together, not the original engine.
 * Explicit U records supply update order, N records supply proximity order.
 * The 5-count drill dump adapter is NOT upstream Interval/Time.time phasing.
 * Only copper/lead, dry mechanical drills, ordinary belts, routers and walls
 * are supported; all are same-team, delta=efficiency=timeScale=1. Drill ore
 * selection/count is supplied. No overflow gates, controlled routers, effects,
 * sleeping/entity scheduling, campaign accounting, topology changes, stack APIs
 * or original serialization. Java float arithmetic is deliberately retained.
 * Belt inventory in observations is derived from the live cargo array, matching
 * the Python adapter; ItemModule synchronization is outside this observation.
 *
 * JDK17 development tool, not a Pythonista dependency. TSV protocol:
 * C name conveyorSpeed
 * B name kind x y rotation cursor routerTime lastInputName progress warmup
 *   dumpTicks copper lead minitem mid oreItem oreCount cargoCount [item y x]...
 * N source [neighbor names]...
 * U name
 * E
 * All B precede N/U; `none` denotes absent input/ore. Each U emits full state
 * and successful delivery events at handleItem entry, before target mutation.
 */
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.StringJoiner;

public final class IntegratedTransportReference {
    static final String[] ITEMS = {"copper", "lead"};
    static final int[] DX = {1, 0, -1, 0}, DY = {0, 1, 0, -1};
    static final float ITEM_SPACE = 0.4f;
    static final int CAPACITY = 3;
    static final Map<String, Build> buildings = new LinkedHashMap<>();
    static final ArrayList<String> deliveries = new ArrayList<>();
    static float conveyorSpeed;
    static int mined;

    static float clamp(float value, float low, float high) {
        return Math.max(low, Math.min(high, value));
    }
    static float approach(float value, float target, float amount) {
        return value + clamp(target - value, -amount, amount);
    }
    static String identifier(String value) {
        if(!value.matches("[A-Za-z][A-Za-z0-9_]*"))
            throw new IllegalArgumentException("invalid identifier: " + value);
        return value;
    }
    static String quote(String value) { return value == null ? "null" : "\"" + value + "\""; }
    static int itemId(String value) {
        if(value.equals("none")) return -1;
        for(int i = 0; i < ITEMS.length; i++) if(value.equals(ITEMS[i])) return i;
        throw new IllegalArgumentException("unsupported item: " + value);
    }
    static float number(String value) {
        float result = Float.parseFloat(value);
        if(!Float.isFinite(result)) throw new IllegalArgumentException("non-finite number");
        return result;
    }
    static Build lookup(String name) {
        Build result = buildings.get(name);
        if(result == null) throw new IllegalArgumentException("unknown building: " + name);
        return result;
    }

    static final class Build {
        final String name, kind;
        final int x, y, size;
        int rotation, cursor, dumpTicks, dominant, oreCount;
        float routerTime, progress, warmup, minitem;
        String lastInput;
        int lastItem = -1, mid, len, lastInserted;
        final int[] items = new int[2], ids = new int[CAPACITY];
        final float[] xs = new float[CAPACITY], ys = new float[CAPACITY];
        final ArrayList<Build> proximity = new ArrayList<>();
        Build next;
        boolean aligned, proximitySet;

        Build(String[] f) {
            if(f.length < 19) throw new IllegalArgumentException("short building record");
            name = identifier(f[1]); kind = f[2];
            if(!kind.equals("mechanical-drill") && !kind.equals("conveyor") &&
                    !kind.equals("router") && !kind.equals("copper-wall"))
                throw new IllegalArgumentException("unsupported building kind");
            size = kind.equals("mechanical-drill") ? 2 : 1;
            x = Integer.parseInt(f[3]); y = Integer.parseInt(f[4]);
            rotation = Integer.parseInt(f[5]); cursor = Integer.parseInt(f[6]);
            routerTime = number(f[7]); lastInput = f[8].equals("none") ? null : identifier(f[8]);
            progress = number(f[9]); warmup = number(f[10]); dumpTicks = Integer.parseInt(f[11]);
            items[0] = Integer.parseInt(f[12]); items[1] = Integer.parseInt(f[13]);
            minitem = number(f[14]); mid = Integer.parseInt(f[15]);
            dominant = itemId(f[16]); oreCount = Integer.parseInt(f[17]);
            len = Integer.parseInt(f[18]);
            // The protocol has 19 fixed fields including the B marker.
            if(f.length != 19 + 3 * len || len < 0 || len > CAPACITY ||
                    rotation < 0 || rotation > 3 || cursor < 0 || cursor > Integer.MAX_VALUE - 8 ||
                    dumpTicks < 0 || dumpTicks > 4 || items[0] < 0 || items[1] < 0 ||
                    items[0] > Integer.MAX_VALUE - items[1] ||
                    minitem < 0 || minitem > 1 || mid < 0 || mid > Math.min(len, 1) ||
                    routerTime < 0 || progress < 0 || warmup < 0 || warmup > 1 ||
                    oreCount < 0 || oreCount > 4)
                throw new IllegalArgumentException("invalid building state");
            if(!kind.equals("conveyor") && len != 0)
                throw new IllegalArgumentException("cargo on non-conveyor");
            if(kind.equals("router") && total() > 1)
                throw new IllegalArgumentException("router inventory exceeds one");
            for(int i = 0; i < len; i++) {
                ids[i] = itemId(f[19 + i * 3]);
                ys[i] = number(f[20 + i * 3]); xs[i] = number(f[21 + i * 3]);
                if(ids[i] < 0 || ys[i] < 0 || ys[i] > 1 || xs[i] < -1 || xs[i] > 1)
                    throw new IllegalArgumentException("invalid conveyor cargo");
            }
        }

        int total() { return items[0] + items[1]; }
        boolean covers(int tx, int ty) { return tx >= x && tx < x + size && ty >= y && ty < y + size; }

        int incoming(Build source) {
            // Edges.getFacingEdge clamps to the source footprint. For size 2,
            // the anchor's lower offset is zero and the upper offset is one.
            int low = -(source.size - 1) / 2, high = source.size / 2;
            int fx = source.x + Math.max(low, Math.min(high, x - source.x));
            int fy = source.y + Math.max(low, Math.min(high, y - source.y));
            // Tile.relativeTo, with fixture-validated edge adjacency.
            if(fx == x - 1 && fy == y) return 0;
            if(fx == x && fy == y - 1) return 1;
            if(fx == x + 1 && fy == y) return 2;
            if(fx == x && fy == y + 1) return 3;
            return -1;
        }

        boolean acceptItem(Build source, int item) {
            if(kind.equals("router")) return lastItem < 0 && total() == 0;
            if(!kind.equals("conveyor") || len >= CAPACITY) return false;
            int incoming = incoming(source);
            if(incoming < 0) return false;
            int direction = Math.abs(incoming - rotation);
            return ((direction == 0 && minitem >= ITEM_SPACE) ||
                    (direction % 2 == 1 && minitem > 0.7f)) &&
                    !(source.kind.equals("conveyor") && next == source);
        }

        void add(int offset) {
            for(int i = Math.max(offset + 1, len); i > offset; i--) {
                ids[i] = ids[i - 1]; xs[i] = xs[i - 1]; ys[i] = ys[i - 1];
            }
            len++;
        }

        void handleItem(Build source, int item) {
            if(kind.equals("conveyor") && len >= CAPACITY) return;
            if(source != this) deliveries.add("{\"source\":" + quote(source.name) +
                ",\"target\":" + quote(name) + ",\"item\":" + quote(ITEMS[item]) +
                ",\"source_rotation\":" + source.rotation + ",\"source_cursor\":" + source.cursor + "}");
            if(kind.equals("router")) {
                items[item]++; lastItem = item; routerTime = 0f; lastInput = source.name;
            } else if(kind.equals("conveyor")) {
                int incoming = incoming(source), ang = incoming - rotation;
                float x = (ang == -1 || ang == 3) ? 1 : (ang == 1 || ang == -3) ? -1 : 0;
                if(Math.abs(incoming - rotation) == 0) {
                    add(0); xs[0] = x; ys[0] = 0; ids[0] = item;
                } else {
                    add(mid); xs[mid] = x; ys[mid] = 0.5f; ids[mid] = item;
                }
            } else items[item]++;
        }

        void incrementDump() { if(!proximity.isEmpty()) cursor = (cursor + 1) % proximity.size(); }
        void offload(int item) {
            int dump = cursor;
            for(int i = 0; i < proximity.size(); i++) {
                incrementDump();
                Build other = proximity.get((i + dump) % proximity.size());
                if(other.acceptItem(this, item)) { other.handleItem(this, item); return; }
            }
            handleItem(this, item);
        }
        boolean dump(int todump) {
            if(total() == 0 || proximity.isEmpty() || (todump >= 0 && items[todump] == 0)) return false;
            int dump = cursor;
            for(int i = 0; i < proximity.size(); i++) {
                Build other = proximity.get((i + dump) % proximity.size());
                int begin = todump < 0 ? 0 : todump, end = todump < 0 ? ITEMS.length : todump + 1;
                for(int item = begin; item < end; item++) {
                    if(items[item] > 0 && other.acceptItem(this, item)) {
                        other.handleItem(this, item); items[item]--; incrementDump(); return true;
                    }
                }
                incrementDump();
            }
            return false;
        }
        void updateDrill() {
            if(++dumpTicks >= 5) { dumpTicks = 0; dump(dominant >= 0 && items[dominant] > 0 ? dominant : -1); }
            if(dominant < 0) return;
            float delay = 650f; // mechanical drill: 600 + hardness(copper/lead)=1 * 50.
            if(total() < 10 && oreCount > 0) {
                warmup = approach(warmup, 1f, 0.015f);
                progress += oreCount * warmup;
            } else { warmup = approach(warmup, 0f, 0.015f); return; }
            if(oreCount > 0 && progress >= delay && total() < 10) {
                int amount = (int)(progress / delay);
                for(int i = 0; i < amount; i++) { mined++; offload(dominant); }
                progress %= delay;
            }
        }
        boolean pass(int item) {
            if(next != null && next.acceptItem(this, item)) { next.handleItem(this, item); return true; }
            return false;
        }
        void updateConveyor() {
            minitem = 1f; mid = 0;
            if(len == 0) return;
            float nextMax = aligned ? 1f - Math.max(ITEM_SPACE - next.minitem, 0) : 1f;
            float moved = conveyorSpeed;
            for(int i = len - 1; i >= 0; i--) {
                float nextpos = (i == len - 1 ? 100f : ys[i + 1]) - ITEM_SPACE;
                float maxmove = clamp(nextpos - ys[i], 0, moved);
                ys[i] += maxmove;
                if(ys[i] > nextMax) ys[i] = nextMax;
                if(ys[i] > 0.5 && i > 0) mid = i - 1;
                xs[i] = approach(xs[i], 0, moved * 2);
                if(ys[i] >= 1f && pass(ids[i])) {
                    if(aligned) next.xs[next.lastInserted] = xs[i];
                    len = Math.min(i, len);
                } else if(ys[i] < minitem) minitem = ys[i];
            }
        }
        Build getTileTarget(int item, boolean set) {
            int counter = rotation;
            for(int i = 0; i < proximity.size(); i++) {
                Build other = proximity.get((i + counter) % proximity.size());
                if(set) rotation = (byte)((rotation + 1) % proximity.size());
                // The upstream from check excludes ONLY overflow gates; none
                // exist in these fixtures, so ordinary lastInput is eligible.
                if(other.acceptItem(this, item)) return other;
            }
            return null;
        }
        void updateRouter() {
            if(lastItem < 0 && total() > 0) lastItem = items[0] > 0 ? 0 : 1;
            if(lastItem < 0) return;
            routerTime += 1f / 8f;
            Build target = getTileTarget(lastItem, false);
            if(target != null && (routerTime >= 1f || !target.kind.equals("router"))) {
                getTileTarget(lastItem, true);
                target.handleItem(this, lastItem);
                items[lastItem]--; lastItem = -1;
            }
        }
        void update() {
            switch(kind) {
                case "mechanical-drill": updateDrill(); break;
                case "conveyor": updateConveyor(); break;
                case "router": updateRouter(); break;
                default: throw new IllegalArgumentException("wall has no updateTile fixture");
            }
        }
        String json() {
            int[] held = items.clone();
            StringJoiner cargo = new StringJoiner(",", "[", "]");
            if(kind.equals("conveyor")) {
                held[0] = held[1] = 0;
                for(int i = 0; i < len; i++) {
                    held[ids[i]]++;
                    cargo.add("{\"item\":" + quote(ITEMS[ids[i]]) + ",\"y\":" + ys[i] + ",\"x\":" + xs[i] + "}");
                }
            }
            return "{\"inventory\":{\"copper\":" + held[0] + ",\"lead\":" + held[1] +
                "},\"belt\":" + cargo + ",\"minitem\":" + minitem + ",\"mid\":" + mid +
                ",\"lastInserted\":" + lastInserted + ",\"cursor\":" + cursor +
                ",\"rotation\":" + rotation + ",\"routerTime\":" + routerTime +
                ",\"lastInput\":" + quote(lastInput) + ",\"progress\":" + progress +
                ",\"warmup\":" + warmup + ",\"dumpTicks\":" + dumpTicks + "}";
        }
    }

    static void connect() {
        for(Build build : buildings.values()) {
            if(build.lastInput != null) lookup(build.lastInput);
            if(!build.proximitySet) throw new IllegalArgumentException("missing proximity record");
            if(!build.kind.equals("conveyor")) continue;
            int tx = build.x + DX[build.rotation], ty = build.y + DY[build.rotation];
            for(Build other : buildings.values()) if(other != build && other.covers(tx, ty)) build.next = other;
            build.aligned = build.next != null && build.next.kind.equals("conveyor") && build.rotation == build.next.rotation;
        }
    }
    static String frame(String update) {
        StringJoiner state = new StringJoiner(",", "{", "}");
        for(Build build : buildings.values()) state.add(quote(build.name) + ":" + build.json());
        return "{\"update\":" + quote(update) + ",\"mined\":" + mined + ",\"deliveries\":[" +
            String.join(",", deliveries) + "],\"buildings\":" + state + "}";
    }
    public static void main(String[] args) throws Exception {
        BufferedReader reader = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String name = null;
        ArrayList<String> frames = new ArrayList<>();
        boolean neighborsStarted = false;
        for(String line; (line = reader.readLine()) != null;) {
            String[] f = line.split("\t", -1);
            switch(f[0]) {
                case "C":
                    if(name != null || f.length != 3) throw new IllegalArgumentException("invalid case start");
                    name = identifier(f[1]); conveyorSpeed = number(f[2]);
                    if(conveyorSpeed < 0 || conveyorSpeed > 1) throw new IllegalArgumentException("invalid speed");
                    buildings.clear(); frames.clear(); deliveries.clear(); mined = 0; neighborsStarted = false;
                    break;
                case "B":
                    if(name == null || neighborsStarted || !frames.isEmpty()) throw new IllegalArgumentException("building outside setup");
                    Build build = new Build(f);
                    if(buildings.putIfAbsent(build.name, build) != null) throw new IllegalArgumentException("duplicate building");
                    break;
                case "N":
                    if(name == null || !frames.isEmpty() || f.length < 2) throw new IllegalArgumentException("invalid proximity record");
                    neighborsStarted = true;
                    Build source = lookup(f[1]);
                    if(source.proximitySet) throw new IllegalArgumentException("duplicate proximity record");
                    source.proximitySet = true;
                    for(int i = 2; i < f.length; i++) {
                        Build other = lookup(f[i]);
                        if(other == source || source.proximity.contains(other)) throw new IllegalArgumentException("invalid proximity member");
                        source.proximity.add(other);
                    }
                    break;
                case "U":
                    if(name == null || f.length != 2) throw new IllegalArgumentException("invalid update record");
                    if(frames.isEmpty()) connect();
                    deliveries.clear(); lookup(f[1]).update(); frames.add(frame(f[1]));
                    break;
                case "E":
                    if(name == null || f.length != 1 || frames.isEmpty()) throw new IllegalArgumentException("invalid case end");
                    System.out.println("{\"name\":" + quote(name) + ",\"frames\":[" + String.join(",", frames) + "]}");
                    name = null;
                    break;
                default: throw new IllegalArgumentException("unknown protocol record");
            }
        }
        if(name != null) throw new IllegalArgumentException("unterminated case");
    }
}
