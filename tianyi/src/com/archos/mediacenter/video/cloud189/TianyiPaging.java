package com.archos.mediacenter.video.cloud189;

import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;

/**
 * Read all pages of a 189Cloud folder. A short response is not proof that a
 * directory is complete: the server is free to cap the requested page size.
 * This class has no Android dependencies so it can be tested on a JVM.
 */
final class TianyiPaging {
    static final int PAGE_SIZE = 100;
    static final int MAX_PAGES = 1000;

    interface Fetcher<T> {
        Page<T> fetch(int pageNumber, int pageSize) throws Exception;
    }

    interface Identity<T> {
        String id(T item);
    }

    static final class Page<T> {
        final List<T> entries;
        final long reportedTotal;

        Page(List<T> entries, long reportedTotal) {
            this.entries = entries;
            this.reportedTotal = reportedTotal;
        }
    }

    static <T> List<T> collect(Fetcher<T> fetcher, Identity<T> identity) throws Exception {
        if (fetcher == null || identity == null)
            throw new IllegalArgumentException("Null paginator input");

        LinkedHashMap<String,T> unique = new LinkedHashMap<>();
        long expectedTotal = -1;
        for (int number = 1; number <= MAX_PAGES; number++) {
            Page<T> response = fetcher.fetch(number, PAGE_SIZE);
            if (response == null || response.entries == null)
                throw new IOException("Cloud directory page has no valid result");
            if (response.reportedTotal >= 0)
                expectedTotal = Math.max(expectedTotal, response.reportedTotal);

            if (response.entries.isEmpty()) {
                if (expectedTotal > unique.size())
                    throw new IOException("Incomplete cloud directory: expected "
                            + expectedTotal + " items, got " + unique.size());
                return new ArrayList<>(unique.values());
            }

            int added = 0;
            for (T entry : response.entries) {
                String id = identity.id(entry);
                if (id == null || id.isEmpty())
                    throw new IOException("Cloud directory row missing a stable ID");
                if (!unique.containsKey(id)) {
                    unique.put(id, entry);
                    added++;
                }
            }

            if (added == 0) {
                // Certain frontends repeat the last page instead of returning
                // an empty page. Only accept that when the reported total
                // has already been collected; otherwise reject partial data.
                if (expectedTotal >= 0 && unique.size() >= expectedTotal)
                    return new ArrayList<>(unique.values());
                throw new IOException("Cloud directory pagination did not advance");
            }
            // Deliberately continue even when response.entries.size() < 100.
        }
        throw new IOException("Cloud directory exceeded pagination safety limit");
    }

    private TianyiPaging() {}
}
