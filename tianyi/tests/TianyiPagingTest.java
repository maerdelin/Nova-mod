package com.archos.mediacenter.video.cloud189;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

public final class TianyiPagingTest {
    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }

    private static List<String> entries(int start, int count) {
        List<String> result = new ArrayList<>();
        for (int i = start; i < start + count; i++) result.add("id-" + i);
        return result;
    }
    private static List<String> read(TianyiPaging.Fetcher<String> fetcher) throws Exception {
        return TianyiPaging.collect(fetcher, x -> x);
    }
    private static void expectIOException(String label, TianyiPaging.Fetcher<String> f) throws Exception {
        try {
            read(f);
            throw new AssertionError("Expected an IOException: " + label);
        } catch (IOException expected) {
            System.out.println("PASS: rejected " + label + ": " + expected.getMessage());
        }
    }

    public static void main(String[] args) throws Exception {
        // The original implementation stopped on the first short page.
        AtomicInteger fetched = new AtomicInteger();
        List<String> limited = read((page, pageSize) -> {
            check(pageSize == 100, "Use conservative page size");
            fetched.incrementAndGet();
            if (page == 1) return new TianyiPaging.Page<>(entries(0, 40), 95);
            if (page == 2) return new TianyiPaging.Page<>(entries(40, 40), 95);
            if (page == 3) return new TianyiPaging.Page<>(entries(80, 15), 95);
            return new TianyiPaging.Page<>(Collections.emptyList(), 95);
        });
        check(limited.size() == 95 && fetched.get() == 3, "Server page clamp caused file loss");
        System.out.println("PASS: server clamps requested page size, no lost MKV rows");

        // A complete one-page directory must NOT make an extra API call.
        AtomicInteger onePageCalls = new AtomicInteger();
        List<String> onePage = read((page, size) -> {
            onePageCalls.incrementAndGet();
            if (page > 1) throw new IOException("Out-of-range page request");
            return new TianyiPaging.Page<>(entries(0, 3), 3);
        });
        check(onePage.size() == 3 && onePageCalls.get() == 1,
                "Requested a page beyond provider total");
        System.out.println("PASS: stop at reported total without extra request");

        List<String> big = read((page, pageSize) -> {
            int start = (page - 1) * pageSize;
            return new TianyiPaging.Page<>(start < 1250 ? entries(start, Math.min(pageSize, 1250 - start))
                    : Collections.emptyList(), 1250);
        });
        check(big.size() == 1250 && big.contains("id-1249"), "Missed late page entry");
        System.out.println("PASS: multi-page 1250-movie directory");

        List<String> overlap = read((page, size) -> {
            if (page == 1) return new TianyiPaging.Page<>(entries(0, 100), 145);
            if (page == 2) return new TianyiPaging.Page<>(entries(95, 50), 145);
            return new TianyiPaging.Page<>(Collections.emptyList(), 145);
        });
        check(overlap.size() == 145, "Overlapping page duplicates not deduplicated");
        System.out.println("PASS: overlapping provider pages are deduplicated");

        List<String> empty = read((page, size) -> new TianyiPaging.Page<>(Collections.emptyList(), 0));
        check(empty.isEmpty(), "Actually empty directory must remain empty");
        System.out.println("PASS: genuinely empty folder");

        expectIOException("truncated count", (page, size) ->
                page == 1 ? new TianyiPaging.Page<>(entries(0, 5), 42)
                        : new TianyiPaging.Page<>(Collections.emptyList(), 42));
        expectIOException("repeated page", (page, size) ->
                new TianyiPaging.Page<>(entries(0, 4), 16));
        expectIOException("malformed empty ID", (page, size) ->
                new TianyiPaging.Page<>(Arrays.asList(""), 1));
        expectIOException("missing page data", (page, size) -> null);
        List<String> absentTotal=read((page, size) ->
            page==1 ? new TianyiPaging.Page<>(entries(0, 7), -1)
                    : new TianyiPaging.Page<>(Collections.emptyList(), -1));
        check(absentTotal.size()==7, "Absent count should use empty-page termination");
        System.out.println("PASS: absent provider total uses empty-page termination");
        expectIOException("pagination upper bound", (page, size) ->
                new TianyiPaging.Page<>(Arrays.asList("id-" + page), TianyiPaging.MAX_PAGES + 10));

        System.out.println("ALL TIANYI PAGING TESTS PASS");
    }
}
