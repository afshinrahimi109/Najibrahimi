package com.najibrahimi.freevpn;

import android.util.Log;

import java.io.OutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * tun2socks مینیمال و از صفر: بستههای IPv4 خام را از TUN میگیرد،
 * برای هر اتصال TCP یه WebSocket به رله VLESS باز میکند و بینشان پل میزند.
 * DNS (UDP/53) هم از طریق یه سوکت محافظتشده جواب داده میشود.
 *
 * محدودیتها: فقط IPv4، فقط TCP (بدون QUIC/UDP عمومی)، بدون بازسازی پنجره پیشرفته.
 */
public class Tun2Socks {
    private static final String TAG = "FreeVPN/Tun2Socks";
    private static final int FIN = 0x01, SYN = 0x02, RST = 0x04, PSH = 0x08, ACK = 0x10;

    private final FreeVpnService service;
    private final OutputStream tunOut;
    private final String host, token, uuidHex;
    private final int port;
    private final boolean tls;
    private final SecureRandom rnd = new SecureRandom();
    private final Map<String, TcpConn> conns = new ConcurrentHashMap<String, TcpConn>();
    private final ExecutorService pool = Executors.newCachedThreadPool();

    public Tun2Socks(FreeVpnService service, OutputStream out, String host, int port,
                     String token, String uuidHex, boolean tls) {
        this.service = service;
        this.tunOut = out;
        this.host = host;
        this.port = port;
        this.token = token;
        this.uuidHex = uuidHex;
        this.tls = tls;
    }

    public void handlePacket(byte[] p, int len) {
        if (len < 20 || (p[0] >> 4) != 4) return;
        int ihl = (p[0] & 0x0f) * 4;
        if (ihl < 20 || len < ihl) return;
        int total = IpUtils.u16(p, 2);
        if (total <= ihl || total > len) return;
        int proto = IpUtils.u8(p, 9);
        if (proto == 6) handleTcp(p, ihl, total);
        else if (proto == 17) handleUdp(p, ihl, total);
    }

    // --------------------------------------------------------------- TCP
    private void handleTcp(byte[] p, int ihl, int total) {
        int tcp = ihl;
        if (total - ihl < 20) return;
        int srcPort = IpUtils.u16(p, tcp);
        int dstPort = IpUtils.u16(p, tcp + 2);
        long seq = IpUtils.u32(p, tcp + 4);
        int dataOff = ((p[tcp + 12] >> 4) & 0x0f) * 4;
        int flags = IpUtils.u8(p, tcp + 13);
        if (dataOff < 20 || total - ihl < dataOff) return;
        int payloadLen = total - ihl - dataOff;

        byte[] localIp = IpUtils.copyIp(p, 12);
        byte[] remoteIp = IpUtils.copyIp(p, 16);
        String key = IpUtils.ipKey(localIp, srcPort) + ">" + IpUtils.ipKey(remoteIp, dstPort);

        if ((flags & RST) != 0) {
            TcpConn old = conns.remove(key);
            if (old != null) old.close();
            return;
        }

        TcpConn c = conns.get(key);
        if ((flags & SYN) != 0 && (flags & ACK) == 0) {
            if (c != null) c.close();
            c = new TcpConn(key, localIp, remoteIp, srcPort, dstPort);
            conns.put(key, c);
            c.clientSeq = (seq + 1) & 0xffffffffL;
            c.serverSeq = rnd.nextInt() & 0xffffffffL;
            final TcpConn fresh = c;
            sendTcp(fresh, SYN | ACK, fresh.serverSeq, fresh.clientSeq, null);
            fresh.serverSeq = (fresh.serverSeq + 1) & 0xffffffffL;
            pool.execute(new Runnable() {
                @Override public void run() { fresh.start(); }
            });
            return;
        }
        if (c == null) return;

        synchronized (c) {
            if (payloadLen > 0) {
                byte[] payload = new byte[payloadLen];
                System.arraycopy(p, tcp + dataOff, payload, 0, payloadLen);
                if (seq == c.clientSeq) {
                    c.clientSeq = (c.clientSeq + payloadLen) & 0xffffffffL;
                    c.sendToRelay(payload);
                }
                sendTcp(c, ACK, c.serverSeq, c.clientSeq, null);
            }
            if ((flags & FIN) != 0) {
                c.clientSeq = (c.clientSeq + 1) & 0xffffffffL;
                sendTcp(c, FIN | ACK, c.serverSeq, c.clientSeq, null);
                c.serverSeq = (c.serverSeq + 1) & 0xffffffffL;
                c.close();
                conns.remove(key);
            }
        }
    }

    private void sendTcp(TcpConn c, int flags, long seq, long ack, byte[] payload) {
        byte[] pkt = IpUtils.buildTcp(c.remoteIp, c.localIp, c.remotePort, c.localPort,
                                      seq, ack, flags, payload, 65535);
        writeTun(pkt);
    }

    private void writeTun(byte[] pkt) {
        synchronized (tunOut) {
            try {
                tunOut.write(pkt);
                tunOut.flush();
            } catch (Exception e) {
                Log.w(TAG, "tun write failed: " + e);
            }
        }
    }

    // --------------------------------------------------------------- UDP / DNS
    private void handleUdp(final byte[] p, final int ihl, final int total) {
        int udp = ihl;
        if (total - ihl < 8) return;
        int srcPort = IpUtils.u16(p, udp);
        int dstPort = IpUtils.u16(p, udp + 2);
        if (dstPort != 53) return;   // بقیه ترافیک UDP (QUIC و...) پشتیبانی نمیشود
        int udpLen = IpUtils.u16(p, udp + 4);
        int dataLen = Math.min(udpLen - 8, total - ihl - 8);
        if (dataLen <= 0) return;
        final byte[] query = new byte[dataLen];
        System.arraycopy(p, udp + 8, query, 0, dataLen);
        final byte[] localIp = IpUtils.copyIp(p, 12);
        final byte[] remoteIp = IpUtils.copyIp(p, 16);
        final int localPort = srcPort;
        pool.execute(new Runnable() {
            @Override public void run() {
                DatagramSocket ds = null;
                try {
                    ds = new DatagramSocket();
                    service.protect(ds);
                    ds.setSoTimeout(5000);
                    ds.send(new DatagramPacket(query, query.length,
                            InetAddress.getByName("1.1.1.1"), 53));
                    byte[] buf = new byte[4096];
                    DatagramPacket resp = new DatagramPacket(buf, buf.length);
                    ds.receive(resp);
                    byte[] answer = Arrays.copyOf(resp.getData(), resp.getLength());
                    writeTun(IpUtils.buildUdp(remoteIp, localIp, 53, localPort, answer));
                } catch (Exception ignored) {
                } finally {
                    if (ds != null) ds.close();
                }
            }
        });
    }

    public void shutdown() {
        for (TcpConn c : conns.values()) c.close();
        conns.clear();
        pool.shutdownNow();
    }

    // --------------------------------------------------------------- اتصال
    private final class TcpConn {
        final String key;
        final byte[] localIp, remoteIp;
        final int localPort, remotePort;
        long clientSeq, serverSeq;
        volatile boolean closed;
        volatile boolean relayReady;
        final List<byte[]> pending = new ArrayList<byte[]>();
        RelaySocket relay;

        TcpConn(String key, byte[] localIp, byte[] remoteIp, int localPort, int remotePort) {
            this.key = key;
            this.localIp = localIp;
            this.remoteIp = remoteIp;
            this.localPort = localPort;
            this.remotePort = remotePort;
        }

        void start() {
            try {
                RelaySocket r = new RelaySocket(host, port, token, uuidHex, tls);
                r.connect(remoteIp, remotePort, service);
                synchronized (this) {
                    relay = r;
                    relayReady = true;
                    for (byte[] chunk : pending) r.send(chunk, chunk.length);
                    pending.clear();
                }
                byte[] buf = new byte[32768];
                while (!closed) {
                    int n = r.recv(buf);
                    if (n <= 0) break;
                    byte[] data = Arrays.copyOf(buf, n);
                    synchronized (this) {
                        if (closed) break;
                        sendTcp(this, PSH | ACK, serverSeq, clientSeq, data);
                        serverSeq = (serverSeq + n) & 0xffffffffL;
                    }
                }
                if (!closed) {
                    synchronized (this) {
                        sendTcp(this, FIN | ACK, serverSeq, clientSeq, null);
                        serverSeq = (serverSeq + 1) & 0xffffffffL;
                    }
                }
            } catch (Exception e) {
                Log.w(TAG, "relay " + key + ": " + e);
            } finally {
                close();
                conns.remove(key);
            }
        }

        void sendToRelay(byte[] data) {
            synchronized (this) {
                if (closed) return;
                if (!relayReady) {
                    pending.add(data);
                    return;
                }
            }
            try {
                relay.send(data, data.length);
            } catch (Exception e) {
                close();
                conns.remove(key);
            }
        }

        void close() {
            closed = true;
            if (relay != null) relay.close();
        }
    }
}
