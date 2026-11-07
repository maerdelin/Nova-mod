package com.archos.mediacenter.video.cloud189;

import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;

/**
 * Collects a COMPLETE single-folder 189Cloud PC listing before the caller may
 * expose it in a DAV 207 response. A partial listing is always an error.
 *
 * OpenList 189pc requests 1000 items per page; the provider's fileListAO.count
 * is the TOTAL number of files + directories, not the number on this page.
 * Some frontends clamp pageSize, so neither a short page nor a repeated last
 * page is sufficient proof of completion when a total is provided.
 */
final class TianyiPaging {
    static final int PAGE_SIZE = 1000;
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

        LinkedHashMap<String, T> unique = new LinkedHashMap<>();
        long expectedTotal = -1;
        for (int number = 1; number <= MAX_PAGES; number++) {
            Page<T> response = fetcher.fetch(number, PAGE_SIZE);
            if (response == null || response.entries == null)
                throw new IOException("Cloud directory page has no valid result");
            if (response.reportedTotal < -1)
                throw new IOException("Cloud directory reports invalid count");
            if (response.reportedTotal >= 0) {
                if (expectedTotal >= 0 && response.reportedTotal != expectedTotal)
                    throw new IOException("Cloud directory changed during pagination");
                expectedTotal = response.reportedTotal;
            }
            if (response.entries.size() > PAGE_SIZE)
                throw new IOException("Cloud directory exceeds requested page size");
            if (response.entries.isEmpty()) {
                if (expectedTotal >= 0 && expectedTotal != unique.size())
                    throw new IOException("Incomplete cloud directory: expected "
                            + expectedTotal + " items, got " + unique.size());
                return new ArrayList<>(unique.values());
            }
            if (expectedTotal == 0)
                throw new IOException("Cloud directory returned rows with a zero count");

            int added = 0;
            for (T entry : response.entries) {
                String id = identity.id(entry);
                if (id == null || id.isEmpty())
                    throw new IOException("Cloud directory row missing stable ID");
                if (!unique.containsKey(id)) {
                    unique.put(id, entry);
                    added++;
                }
            }
            if (expectedTotal >= 0 && unique.size() > expectedTotal)
                throw new IOException("Cloud directory exceeded reported total");
            if (expectedTotal >= 0 && unique.size() == expectedTotal)
                return new ArrayList<>(unique.values());
            if (added == 0)
                throw new IOException("Cloud directory pagination stopped advancing");

            // Never stop just because the page is shorter than PAGE_SIZE:
            // provider-side caps can make EVERY page short. Continue until
            // the authoritative count is satisfied or a real empty page ends
            // a count-less listing. No partial DAV response is returned.
        }
        throw new IOException("Cloud directory exceeded pagination safety limit");
    }

    private TianyiPaging() {}
}
