package com.archos.mediacenter.video.cloud189;

import java.io.IOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.FutureTask;

/**
 * Android-independent, bounded cache of COMPLETE cloud directory snapshots.
 *
 * NOVA resolves every leaf/HEAD/GET by its DAV path, which otherwise re-lists
 * every ancestor folder on every request. A successful snapshot is reused
 * briefly; a failed/partial fetch is NEVER cached. Simultaneous readers share
 * a single in-flight fetch. Clearing the cache invalidates in-flight results
 * so a previous cloud account cannot leak into a newly logged-in account.
 */
final class TianyiDirectoryCache<T> {
    interface Loader<T> {
        List<T> load() throws Exception;
    }

    static final long DEFAULT_TTL_MS = 60_000L;
    static final int DEFAULT_MAX_FOLDERS = 32;
    static final int DEFAULT_MAX_ENTRIES = 60_000;

    private static final class Snapshot<T> {
        final List<T> entries;
        final long createdAt;
        Snapshot(List<T> entries, long createdAt) {
            this.entries = entries;
            this.createdAt = createdAt;
        }
    }
    private static final class Pending<T> {
        final FutureTask<List<T>> task;
        final long generation;
        Pending(FutureTask<List<T>> task,long generation) {
            this.task=task;
            this.generation=generation;
        }
    }

    private final long ttlMs;
    private final int maxFolders;
    private final int maxEntries;
    private int cachedEntries=0;
    private long generation=0;
    private final LinkedHashMap<String,Snapshot<T>> complete =
            new LinkedHashMap<>(16,0.75f,true);
    private final Map<String,Pending<T>> inFlight=new HashMap<>();

    TianyiDirectoryCache() {
        this(DEFAULT_TTL_MS,DEFAULT_MAX_FOLDERS,DEFAULT_MAX_ENTRIES);
    }
    TianyiDirectoryCache(long ttlMs,int maxFolders,int maxEntries) {
        if(ttlMs<1 || maxFolders<1 || maxEntries<1)
            throw new IllegalArgumentException("Cache limits must be positive");
        this.ttlMs=ttlMs;
        this.maxFolders=maxFolders;
        this.maxEntries=maxEntries;
    }
    synchronized void clear() {
        generation++;
        complete.clear();
        cachedEntries=0;
        inFlight.clear();
    }
    List<T> get(String folderId,Loader<T> loader) throws Exception {
        if(folderId==null || loader==null)throw new IllegalArgumentException();
        Pending<T> pending;
        boolean owner=false;
        synchronized(this) {
            Snapshot<T> previous=complete.get(folderId);
            if(previous!=null) {
                if(System.currentTimeMillis()-previous.createdAt < ttlMs)
                    return previous.entries;
                complete.remove(folderId);
                cachedEntries-=previous.entries.size();
            }
            pending=inFlight.get(folderId);
            if(pending==null) {
                pending=new Pending<>(new FutureTask<>(loader::load),generation);
                inFlight.put(folderId,pending);
                owner=true;
            }
        }
        if(owner)pending.task.run();
        try {
            List<T> loaded=pending.task.get();
            if(loaded==null)throw new IOException("Null cloud directory snapshot");
            synchronized(this) {
                if(pending.generation!=generation)
                    throw new IOException("Cloud directory invalidated during request");
                if(owner) {
                    // Always publish an immutable copy, never caller-owned state.
                    List<T> snapshot=java.util.Collections.unmodifiableList(
                            new ArrayList<>(loaded));
                    // A verified empty listing is returned to the current caller
                    // but is never cached: a transient upstream zero count
                    // must not poison subsequent NOVA navigation.
                    if(!snapshot.isEmpty() && snapshot.size()<=maxEntries) {
                        Snapshot<T> old=complete.put(folderId,
                                new Snapshot<>(snapshot,System.currentTimeMillis()));
                        if(old!=null)cachedEntries-=old.entries.size();
                        cachedEntries+=snapshot.size();
                        evictOldest();
                    }
                    return snapshot;
                }
            }
            return loaded; // the single-flight owner publishes its copy
        }catch(ExecutionException e) {
            Throwable cause=e.getCause();
            if(cause instanceof Exception)throw (Exception)cause;
            throw new IOException("Cloud directory read crashed",cause);
        }catch(InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IOException("Cloud directory read interrupted",e);
        }finally {
            if(owner) {
                synchronized(this) {
                    if(inFlight.get(folderId)==pending)
                        inFlight.remove(folderId);
                }
            }
        }
    }
    private void evictOldest() {
        Iterator<Map.Entry<String,Snapshot<T>>> iterator=complete.entrySet().iterator();
        while((cachedEntries>maxEntries || complete.size()>maxFolders)
                && iterator.hasNext()) {
            Snapshot<T> removed=iterator.next().getValue();
            cachedEntries-=removed.entries.size();
            iterator.remove();
        }
    }
}
