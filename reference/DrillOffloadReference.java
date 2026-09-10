// SPDX-License-Identifier: GPL-3.0-only
// Extracted from Mindustry v159.7, c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c:
// BuildingComp.offload/dump/incrementDump and the dry DrillBuild.updateTile branch.
// Adapters supply fixed proximity, item IDs 0/1, explicit timer boundaries and
// scripted receivers. No original engine, campaign production, effects or scheduling.
import java.io.*;
import java.util.*;

public final class DrillOffloadReference {
    static final String[] ITEMS = {"copper", "lead"};
    static final class Receiver {
        String name;
        int mask, capacity;
        int[] inventory = new int[2];
        Receiver(String name, int mask, int capacity) {
            this.name = name; this.mask = mask; this.capacity = capacity;
        }
    }
    static final class Drill {
        String name;
        int cdump, dominant, oreCount, mined;
        float progress, warmup = 1f;
        int[] items = new int[2];
        ArrayList<Receiver> proximity = new ArrayList<>();
        ArrayList<String> dumpAttempts = new ArrayList<>();
        ArrayList<String> offloadAttempts = new ArrayList<>();
        ArrayList<String> events = new ArrayList<>();
        ArrayList<String> frames = new ArrayList<>();
        ArrayList<String> record;
        Float firstOffloadProgress;

        boolean accept(Receiver other, int item) {
            boolean result = (other.mask & (1 << item)) != 0
                && other.inventory[0] + other.inventory[1] < other.capacity;
            if(record != null) record.add("{\"neighbor\":" + quote(other.name) + ",\"item\":" + quote(ITEMS[item])
                + ",\"accepted\":" + result + ",\"cursor_before\":" + cdump + "}");
            return result;
        }
        void incrementDump(int prox) {
            if(prox != 0) cdump = (cdump + 1) % prox;
        }
        void event(String value) {
            if(events.isEmpty() || !events.get(events.size() - 1).equals(value)) events.add(value);
        }
        boolean offload(int item) {
            // produced(item, 1) updates campaign accounting upstream; excluded here.
            event("offload");
            record = firstOffloadProgress == null ? offloadAttempts : null;
            if(firstOffloadProgress == null) firstOffloadProgress = progress;
            int dump = this.cdump;
            for(int i = 0; i < proximity.size(); i++) {
                incrementDump(proximity.size());
                Receiver other = proximity.get((i + dump) % proximity.size());
                if(accept(other, item)) {
                    other.inventory[item]++;
                    return true; // Adapter observation; upstream method returns void.
                }
            }
            items[item]++;
            return false;
        }
        boolean dump(int todump) {
            event("dump");
            record = dumpAttempts;
            if(items[0] + items[1] == 0 || proximity.size() == 0
                    || (todump >= 0 && items[todump] == 0)) return false;
            int dump = this.cdump;
            if(todump < 0) {
                for(int i = 0; i < proximity.size(); i++) {
                    Receiver other = proximity.get((i + dump) % proximity.size());
                    for(int ii = 0; ii < ITEMS.length; ii++) {
                        if(items[ii] == 0) continue;
                        if(accept(other, ii)) {
                            other.inventory[ii]++;
                            items[ii]--;
                            incrementDump(proximity.size());
                            return true;
                        }
                    }
                    incrementDump(proximity.size());
                }
            } else {
                for(int i = 0; i < proximity.size(); i++) {
                    Receiver other = proximity.get((i + dump) % proximity.size());
                    if(accept(other, todump)) {
                        other.inventory[todump]++;
                        items[todump]--;
                        incrementDump(proximity.size());
                        return true;
                    }
                    incrementDump(proximity.size());
                }
            }
            return false;
        }
        void tick(boolean periodicDue) {
            if(periodicDue) dump(dominant >= 0 && items[dominant] > 0 ? dominant : -1);
            if(dominant < 0) return;
            // timeDrilled, speed diagnostics and visual effects do not feed this
            // extracted inventory/progress branch. delta=speed=efficiency=1.
            float delay = 650f; // mechanical drill 600 + hardness 1 * 50.
            if(items[0] + items[1] < 10 && oreCount > 0) {
                warmup = Math.min(warmup + 0.015f, 1f);
                progress += oreCount * warmup;
            } else {
                warmup = Math.max(warmup - 0.015f, 0f);
                return;
            }
            if(oreCount > 0 && progress >= delay && items[0] + items[1] < 10) {
                int amount = (int)(progress / delay);
                for(int i = 0; i < amount; i++) {
                    mined++; // Adapter count only; not original campaign statistics.
                    offload(dominant);
                }
                progress %= delay;
            }
        }
        void call(String kind) {
            dumpAttempts.clear(); offloadAttempts.clear(); events.clear();
            firstOffloadProgress = null; record = null;
            Boolean result = null;
            if(kind.equals("tick") || kind.equals("dump_tick")) tick(kind.equals("dump_tick"));
            else result = offload(itemId(kind));
            StringJoiner received = new StringJoiner(",", "{", "}");
            for(Receiver other : proximity) received.add(quote(other.name) + ":" + inventory(other.inventory));
            StringJoiner eventText = new StringJoiner(",", "[", "]");
            for(String value : events) eventText.add(quote(value));
            frames.add("{\"call\":" + quote(kind) + ",\"result\":" + result
                + ",\"cursor\":" + cdump + ",\"progress\":" + progress + ",\"mined\":" + mined
                + ",\"inventory\":" + inventory(items) + ",\"receipts\":" + received
                + ",\"events\":" + eventText + ",\"offload_progress\":" + firstOffloadProgress
                + ",\"dump_attempts\":[" + String.join(",", dumpAttempts)
                + "],\"offload_attempts\":[" + String.join(",", offloadAttempts) + "]}");
        }
    }
    // Fixture validator restricts identifiers to ASCII letters/digits/underscore.
    static String quote(String value) { return "\"" + value + "\""; }
    static int itemId(String value) {
        if(value.equals("copper")) return 0;
        if(value.equals("lead")) return 1;
        if(value.equals("none")) return -1;
        throw new IllegalArgumentException("unknown item: " + value);
    }
    static String inventory(int[] values) {
        return "{\"copper\":" + values[0] + ",\"lead\":" + values[1] + "}";
    }
    public static void main(String[] args) throws Exception {
        BufferedReader reader = new BufferedReader(new InputStreamReader(System.in, "UTF-8"));
        Drill drill = null;
        String line;
        while((line = reader.readLine()) != null) {
            String[] fields = line.split("\t");
            switch(fields[0]) {
                case "C":
                    drill = new Drill(); drill.name = fields[1];
                    drill.cdump = Integer.parseInt(fields[2]); drill.dominant = itemId(fields[3]);
                    drill.oreCount = Integer.parseInt(fields[4]); drill.progress = Float.parseFloat(fields[5]);
                    drill.items[0] = Integer.parseInt(fields[6]); drill.items[1] = Integer.parseInt(fields[7]);
                    break;
                case "N":
                    drill.proximity.add(new Receiver(fields[1], Integer.parseInt(fields[2]), Integer.parseInt(fields[3])));
                    break;
                case "D": drill.call(fields[1]); break;
                case "E":
                    System.out.println("{\"name\":" + quote(drill.name) + ",\"frames\":["
                        + String.join(",", drill.frames) + "]}");
                    break;
                default: throw new IllegalArgumentException("unknown protocol record");
            }
        }
    }
}
