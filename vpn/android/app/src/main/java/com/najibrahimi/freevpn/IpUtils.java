package com.najibrahimi.freevpn;

import java.io.ByteArrayOutputStream;
import java.util.Random;

/**
 * ابزارهای ساخت بسته IPv4/TCP/UDP و محاسبه checksum — پیادهسازی از صفر.
 * فقط IPv4 و TCP/UDP ساده پشتیبانی میشود (برای یه VPN شخصی کافی است).
 */
public final class IpUtils {
    private static final Random RND = new Random();

    private IpUtils() {}

    public static int u8(byte[] b, int o) { return b[o] & 0xff; }

    public static int u16(byte[] b, int o) {
        return ((b[o] & 0xff) << 8) | (b[o + 1] & 0xff);
    }

    public static long u32(byte[] b, int o) {
        return ((long) (b[o] & 0xff) << 24) | ((long) (b[o + 1] & 0xff) << 16) |
               ((long) (b[o + 2] & 0xff) << 8) | (long) (b[o + 3] & 0xff);
    }

    public static void put16(byte[] b, int o, int v) {
        b[o] = (byte) ((v >> 8) & 0xff);
        b[o + 1] = (byte) (v & 0xff);
    }

    public static void put32(byte[] b, int o, long v) {
        b[o] = (byte) ((v >> 24) & 0xff);
        b[o + 1] = (byte) ((v >> 16) & 0xff);
        b[o + 2] = (byte) ((v >> 8) & 0xff);
        b[o + 3] = (byte) (v & 0xff);
    }

    public static byte[] copyIp(byte[] p, int off) {
        return new byte[] { p[off], p[off + 1], p[off + 2], p[off + 3] };
    }

    /** checksum یکنواخت اینترنت (RFC 1071). initial برای pseudo-header TCP است. */
    public static int checksum(byte[] b, int off, int len, long initial) {
        long sum = initial;
        int i = 0;
        while (i + 1 < len) {
            sum += ((b[off + i] & 0xff) << 8) | (b[off + i + 1] & 0xff);
            i += 2;
        }
        if (i < len) {
            sum += (b[off + i] & 0xff) << 8;
        }
        while ((sum >> 16) != 0) {
            sum = (sum & 0xffff) + (sum >> 16);
        }
        return (int) (~sum & 0xffff);
    }

    private static void ipHeader(byte[] pkt, byte[] src, byte[] dst, int proto, int payloadLen) {
        pkt[0] = 0x45;              // IPv4, IHL=5 (20 bytes)
        pkt[1] = 0;                 // DSCP/ECN
        put16(pkt, 2, 20 + payloadLen);
        put16(pkt, 4, RND.nextInt(0xffff)); // ID
        put16(pkt, 6, 0x4000);     // Don't Fragment
        pkt[8] = 64;                // TTL
        pkt[9] = (byte) proto;
        put16(pkt, 10, 0);         // checksum موقتاً صفر
        System.arraycopy(src, 0, pkt, 12, 4);
        System.arraycopy(dst, 0, pkt, 16, 4);
        put16(pkt, 10, checksum(pkt, 0, 20, 0));
    }

    /** بسته TCP کامل (بدون options) برای نوشتن در TUN. */
    public static byte[] buildTcp(byte[] srcIp, byte[] dstIp, int srcPort, int dstPort,
                                  long seq, long ack, int flags, byte[] payload, int window) {
        int dataLen = payload == null ? 0 : payload.length;
        byte[] pkt = new byte[20 + 20 + dataLen];
        ipHeader(pkt, srcIp, dstIp, 6, 20 + dataLen);

        int t = 20;
        put16(pkt, t, srcPort);
        put16(pkt, t + 2, dstPort);
        put32(pkt, t + 4, seq & 0xffffffffL);
        put32(pkt, t + 8, ack & 0xffffffffL);
        pkt[t + 12] = (byte) (5 << 4); // data offset = 5 words
        pkt[t + 13] = (byte) flags;
        put16(pkt, t + 14, window);
        put16(pkt, t + 16, 0);        // checksum موقتاً صفر
        put16(pkt, t + 18, 0);        // urgent pointer
        if (dataLen > 0) {
            System.arraycopy(payload, 0, pkt, 40, dataLen);
        }

        // pseudo-header: src + dst + zero + protocol + طول TCP
        long pseudo = word(srcIp, 0) + word(srcIp, 2) + word(dstIp, 0) + word(dstIp, 2)
                    + 6 + (20 + dataLen);
        put16(pkt, t + 16, checksum(pkt, t, 20 + dataLen, pseudo));
        return pkt;
    }

    /** بسته UDP کامل؛ checksum UDP در IPv4 میتواند صفر باشد (RFC 768). */
    public static byte[] buildUdp(byte[] srcIp, byte[] dstIp, int srcPort, int dstPort,
                                  byte[] payload) {
        int dataLen = payload == null ? 0 : payload.length;
        byte[] pkt = new byte[20 + 8 + dataLen];
        ipHeader(pkt, srcIp, dstIp, 17, 8 + dataLen);
        int u = 20;
        put16(pkt, u, srcPort);
        put16(pkt, u + 2, dstPort);
        put16(pkt, u + 4, 8 + dataLen);
        put16(pkt, u + 6, 0);
        if (dataLen > 0) {
            System.arraycopy(payload, 0, pkt, 28, dataLen);
        }
        return pkt;
    }

    private static long word(byte[] b, int o) {
        return ((b[o] & 0xff) << 8) | (b[o + 1] & 0xff);
    }

    public static byte[] hexToBytes(String hex) {
        String s = hex.replace("-", "").trim();
        if (s.length() != 32) {
            throw new IllegalArgumentException("UUID must be 32 hex chars");
        }
        byte[] out = new byte[16];
        for (int i = 0; i < 16; i++) {
            out[i] = (byte) Integer.parseInt(s.substring(i * 2, i * 2 + 2), 16);
        }
        return out;
    }

    public static String ipKey(byte[] ip, int port) {
        return (ip[0] & 0xff) + "." + (ip[1] & 0xff) + "." +
               (ip[2] & 0xff) + "." + (ip[3] & 0xff) + ":" + port;
    }

    public static byte[] concat(byte[] a, byte[] b) {
        ByteArrayOutputStream out = new ByteArrayOutputStream(a.length + b.length);
        out.write(a, 0, a.length);
        out.write(b, 0, b.length);
        return out.toByteArray();
    }
}
