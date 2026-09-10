// SPDX-License-Identifier: GPL-3.0-only
// Extracted from Mindustry v159.7, c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c:
// BuildingComp.dump(Item)/incrementDump and DrillBuild's periodic item selector.
// Test adapters supply explicit proximity, item IDs 0/1 and scripted receivers.
// This is not the original game, mining, timer, scheduler or receiver engine.
import java.io.*;
import java.util.*;

public final class DrillDumpReference {
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
        int cdump;
        int dominant;
        int[] items = new int[2];
        ArrayList<Receiver> proximity = new ArrayList<>();
        ArrayList<String> attempts = new ArrayList<>();
        ArrayList<String> frames = new ArrayList<>();

        boolean accept(Receiver other, int item) {
            boolean result = (other.mask & (1 << item)) != 0
                && other.inventory[0] + other.inventory[1] < other.capacity;
            attempts.add("{\"neighbor\":" + quote(other.name) + ",\"item\":" + quote(ITEMS[item])
                + ",\"accepted\":" + result + ",\"cursor_before\":" + cdump + "}");
            return result;
        }

        void incrementDump(int prox) {
            if(prox != 0) cdump = (cdump + 1) % prox;
        }

        boolean dump(int todump) {
            // hasItems and inherited canDump are true in the extracted scope.
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

        void call(String kind) {
            attempts.clear();
            int selected = kind.equals("drill") ? (dominant >= 0 && items[dominant] > 0 ? dominant : -1)
                : itemId(kind);
            boolean result = dump(selected);
            StringJoiner received = new StringJoiner(",", "{", "}");
            for(Receiver other : proximity) received.add(quote(other.name) + ":" + inventory(other.inventory));
            frames.add("{\"call\":" + quote(kind) + ",\"selected\":"
                + (selected < 0 ? "null" : quote(ITEMS[selected])) + ",\"result\":" + result
                + ",\"cursor\":" + cdump + ",\"inventory\":" + inventory(items)
                + ",\"receipts\":" + received + ",\"attempts\":[" + String.join(",", attempts) + "]}");
        }
    }

    // Input identifiers are restricted to ASCII letters/digits/underscore by
    // the Python fixture validator; they cannot contain JSON syntax.
    static String quote(String value) { return "\"" + value + "\""; }
    static int itemId(String value) {
        if(value.equals("copper")) return 0;
        if(value.equals("lead")) return 1;
        if(value.equals("any")) return -1;
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
            String[] fields = line.split("\\t");
            switch(fields[0]) {
                case "C":
                    drill = new Drill(); drill.name = fields[1];
                    drill.cdump = Integer.parseInt(fields[2]); drill.dominant = itemId(fields[3]);
                    drill.items[0] = Integer.parseInt(fields[4]); drill.items[1] = Integer.parseInt(fields[5]);
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
