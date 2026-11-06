package com.archos.mediacenter.video.cloud189;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import org.json.JSONException;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.SecureRandom;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Credentials are kept in AndroidKeyStore-protected SharedPreferences, never in
 * the ordinary NOVA WebDAV credentials database, a URI, or a log statement.
 * The non-secret loopback capability is stable across process restarts.
 *
 * OpenList 189CloudPC v4.2.9 is the behavioral reference, not a copied binary.
 */
final class TianyiStore {
    private static final String PREFS = "nova_tianyi_cloud_v1";
    private static final String ALIAS = "nova_tianyi_cloud_v1_aes";
    private static final String RECORD = "encrypted_record_v1";
    private static final SecureRandom RNG = new SecureRandom();
    private final SharedPreferences prefs;

    TianyiStore(Context context) {
        prefs = context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static final class Saved {
        String accessToken = "";
        String refreshToken = "";
        String userFinger = "";
        String pathKey = "";
    }

    synchronized Saved read() throws Exception {
        Saved result = new Saved();
        String encrypted = prefs.getString(RECORD, "");
        if (encrypted == null || encrypted.isEmpty()) return result;
        String[] pieces = encrypted.split(":", -1);
        if (pieces.length != 2) throw new SecurityException("Invalid saved Tianyi record");
        byte[] nonce = Base64.decode(pieces[0], Base64.NO_WRAP);
        byte[] ciphertext = Base64.decode(pieces[1], Base64.NO_WRAP);
        if (nonce.length != 12 || ciphertext.length < 16) {
            throw new SecurityException("Invalid saved Tianyi record length");
        }
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, nonce));
        cipher.updateAAD(PREFS.getBytes(StandardCharsets.UTF_8));
        JSONObject obj = new JSONObject(new String(cipher.doFinal(ciphertext), StandardCharsets.UTF_8));
        result.accessToken = obj.optString("access", "");
        result.refreshToken = obj.optString("refresh", "");
        result.userFinger = obj.optString("finger", "");
        result.pathKey = obj.optString("path", "");
        return result;
    }

    private synchronized void write(Saved value) throws Exception {
        JSONObject obj = new JSONObject();
        obj.put("access", value.accessToken);
        obj.put("refresh", value.refreshToken);
        obj.put("finger", value.userFinger);
        obj.put("path", value.pathKey);
        byte[] nonce = new byte[12];
        RNG.nextBytes(nonce);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key(), new GCMParameterSpec(128, nonce));
        cipher.updateAAD(PREFS.getBytes(StandardCharsets.UTF_8));
        byte[] ciphertext = cipher.doFinal(obj.toString().getBytes(StandardCharsets.UTF_8));
        String packed = Base64.encodeToString(nonce, Base64.NO_WRAP) + ":" +
                Base64.encodeToString(ciphertext, Base64.NO_WRAP);
        if (!prefs.edit().putString(RECORD, packed).commit()) {
            throw new IllegalStateException("Cannot persist Tianyi login credentials");
        }
    }

    synchronized String getOrCreateFinger() throws Exception {
        Saved saved = read();
        if (saved.userFinger.isEmpty()) {
            long n = 1000000000L + (Math.abs(RNG.nextLong()) % 9000000000L);
            saved.userFinger = Long.toString(n);
            write(saved);
        }
        return saved.userFinger;
    }

    synchronized String getOrCreatePathKey() throws Exception {
        Saved saved = read();
        if (saved.pathKey.isEmpty()) {
            byte[] random = new byte[24];
            RNG.nextBytes(random);
            StringBuilder key = new StringBuilder(48);
            for (byte b : random) {
                key.append(Character.forDigit((b >>> 4) & 15, 16));
                key.append(Character.forDigit(b & 15, 16));
            }
            saved.pathKey = key.toString();
            write(saved);
        }
        return saved.pathKey;
    }

    synchronized void saveTokens(String access, String refresh) throws Exception {
        if (access == null || access.isEmpty() || refresh == null || refresh.isEmpty()) {
            throw new IllegalArgumentException("Both tokens required");
        }
        Saved saved = read();
        saved.accessToken = access;
        saved.refreshToken = refresh;
        write(saved); // commit synchronously: provider may rotate the refresh token
    }

    synchronized void clearTokens() throws Exception {
        Saved saved = read();
        saved.accessToken = "";
        saved.refreshToken = "";
        write(saved);
    }

    private static SecretKey key() throws Exception {
        KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
        ks.load(null);
        KeyStore.Entry entry = ks.getEntry(ALIAS, null);
        if (entry instanceof KeyStore.SecretKeyEntry) {
            return ((KeyStore.SecretKeyEntry) entry).getSecretKey();
        }
        // v6.6.4 uses minSdk >= 23. Never silently fall back to plain text.
        if (Build.VERSION.SDK_INT < 23) {
            throw new SecurityException("Tianyi requires Android 6 or newer");
        }
        KeyGenerator gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        gen.init(new KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build());
        return gen.generateKey();
    }
}
