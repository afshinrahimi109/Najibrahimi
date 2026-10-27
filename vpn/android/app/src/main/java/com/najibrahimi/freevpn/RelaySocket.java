package com.najibrahimi.freevpn;

import android.net.VpnService;
import android.util.Base64;
import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.security.SecureRandom;

import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;

/**
 * یک اتصال WebSocket = یک جریان TCP داخل تونل VLESS.
 * هندشیک RFC 6455، فریمهای maskدار سمت کلاینت، و هدر باینری VLESS — همه از صفر.
 */
public class RelaySocket {
    private static final String TAG = "FreeVPN/Relay";
    private final String host, token, uuidHex;
    private final int port;
    private final boolean tls;
    private final SecureRandom rnd = new SecureRandom();

    private Socket socket;
    private InputStream in;
    private OutputStream out;
    private int stripHeader = 2;  // هدر پاسخ VLESS: [version, addon_len]

    public RelaySocket(String host, int port, String token, String uuidHex, boolean tls) {
        this.host = host;
        this.port = port;
        this.token = token;
        this.uuidHex = uuidHex;
        this.tls = tls;
    }

    public void connect(byte[] targetIp, int targetPort, VpnService service) throws IOException {
        Socket raw = new Socket();
        if (service != null) {
            service.protect(raw);  // ترافیک خود اپ وارد TUN نشود
        }
        raw.connect(new InetSocketAddress(host, port), 15000);
        raw.setSoTimeout(120000);
        raw.setTcpNoDelay(true);
        if (tls) {
            SSLSocket ssl = (SSLSocket) SSLSocketFactory.getDefault()
                    .createSocket(raw, host, port, true);
            ssl.startHandshake();
            socket = ssl;
        } else {
            socket = raw;
        }
        in = socket.getInputStream();
        out = socket.getOutputStream();
        wsHandshake();
        sendFrame(vlessHeader(targetIp, targetPort), 0x2);
        Log.d(TAG, "tunnel ready -> " + targetPort);
    }

    private void wsHandshake() throws IOException {
        byte[] keyBytes = new byte[16];
        rnd.nextBytes(keyBytes);
        String key = Base64.encodeToString(keyBytes, Base64.NO_WRAP);
        String hostHeader = (port == 80 || port == 443) ? host : host + ":" + port;
        String request = "GET /" + token + " HTTP/1.1\r\n"
                + "Host: " + hostHeader + "\r\n"
                + "Upgrade: websocket\r\n"
                + "Connection: Upgrade\r\n"
                + "Sec-WebSocket-Key: " + key + "\r\n"
                + "Sec-WebSocket-Version: 13\r\n\r\n";
        out.write(request.getBytes("US-ASCII"));
        out.flush();

        ByteArrayOutputStream head = new ByteArrayOutputStream();
        int matched = 0;
        byte[] pattern = { '\r', '\n', '\r', '\n' };
        while (matched < 4 && head.size() < 16384) {
            int c = in.read();
            if (c < 0) break;
            head.write(c);
            if (c == pattern[matched]) {
                matched++;
            } else {
                matched = (c == '\r') ? 1 : 0;
            }
        }
        String first = head.toString("US-ASCII").split("\r\n")[0];
        if (!first.contains(" 101 ")) {
            throw new IOException("WebSocket handshake failed: " + first);
        }
    }

    private byte[] vlessHeader(byte[] ip, int targetPort) {
        byte[] uuid = IpUtils.hexToBytes(uuidHex);
        byte[] h = new byte[1 + 16 + 1 + 1 + 2 + 1 + 4];
        int o = 0;
        h[o++] = 0;                       // version
        System.arraycopy(uuid, 0, h, o, 16); o += 16;
        h[o++] = 0;                       // addons length
        h[o++] = 1;                       // command: TCP
        IpUtils.put16(h, o, targetPort); o += 2;
        h[o++] = 1;                       // address type: IPv4
        System.arraycopy(ip, 0, h, o, 4);
        return h;
    }

    private void sendFrame(byte[] data, int opcode) throws IOException {
        int len = data.length;
        ByteArrayOutputStream f = new ByteArrayOutputStream(len + 16);
        f.write(0x80 | opcode);
        if (len < 126) {
            f.write(0x80 | len);
        } else if (len < 65536) {
            f.write(0x80 | 126);
            f.write((len >> 8) & 0xff);
            f.write(len & 0xff);
        } else {
            f.write(0x80 | 127);
            for (int i = 7; i >= 0; i--) f.write((int) (((long) len >> (8 * i)) & 0xff));
        }
        byte[] mask = new byte[4];
        rnd.nextBytes(mask);
        f.write(mask, 0, 4);
        for (int i = 0; i < len; i++) f.write(data[i] ^ mask[i % 4]);
        out.write(f.toByteArray());
        out.flush();
    }

    public void send(byte[] data, int len) throws IOException {
        byte[] chunk = new byte[len];
        System.arraycopy(data, 0, chunk, 0, len);
        sendFrame(chunk, 0x2);
    }

    private byte[] readFrame() throws IOException {
        int b0 = in.read();
        if (b0 < 0) return null;
        int b1 = in.read();
        if (b1 < 0) return null;
        int opcode = b0 & 0x0f;
        boolean masked = (b1 & 0x80) != 0;
        long len = b1 & 0x7f;
        if (len == 126) {
            len = ((long) (in.read() & 0xff) << 8) | (in.read() & 0xff);
        } else if (len == 127) {
            len = 0;
            for (int i = 0; i < 8; i++) len = (len << 8) | (in.read() & 0xff);
        }
        if (len > 1024 * 1024) throw new IOException("websocket frame too large");
        byte[] mask = new byte[4];
        if (masked) readFully(mask, 4);
        byte[] payload = new byte[(int) len];
        readFully(payload, (int) len);
        if (masked) {
            for (int i = 0; i < payload.length; i++) payload[i] ^= mask[i % 4];
        }
        if (opcode == 0x9) {           // ping -> pong
            sendFrame(payload, 0xA);
            return readFrame();
        }
        if (opcode == 0xA) return readFrame();
        if (opcode == 0x8) return null;
        return payload;
    }

    private void readFully(byte[] buf, int len) throws IOException {
        int off = 0;
        while (off < len) {
            int n = in.read(buf, off, len - off);
            if (n < 0) throw new IOException("tunnel closed");
            off += n;
        }
    }

    /** -> تعداد بایتهای تحویلشده، یا -1 یعنی بسته شدن تونل. */
    public int recv(byte[] buf) throws IOException {
        while (true) {
            byte[] frame = readFrame();
            if (frame == null) return -1;
            int off = 0;
            if (stripHeader > 0) {
                off = Math.min(stripHeader, frame.length);
                stripHeader -= off;
            }
            int n = frame.length - off;
            if (n == 0) continue;
            if (n > buf.length) n = buf.length;
            System.arraycopy(frame, off, buf, 0, n);
            return n;
        }
    }

    public void close() {
        try { if (socket != null) socket.close(); } catch (IOException ignored) {}
    }
}
