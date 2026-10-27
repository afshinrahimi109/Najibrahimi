package com.najibrahimi.freevpn;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.VpnService;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.net.URLDecoder;

/** رابط کاربری ساده: لینک vless:// را بچسبان، وصل شو. */
public class MainActivity extends Activity {
    private EditText linkEdit, hostEdit, tokenEdit, uuidEdit, portEdit;
    private TextView status;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("freevpn", Context.MODE_PRIVATE);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(48, 48, 48, 48);

        TextView title = new TextView(this);
        title.setText("🔐 FreeVPN — ساختهشده از صفر");
        title.setTextSize(22);
        root.addView(title);

        TextView help = new TextView(this);
        help.setText("لینک vless:// سرورت (از gen_config.py یا صفحه /<TOKEN>/) را اینجا بچسبان.");
        help.setPadding(0, 12, 0, 24);
        root.addView(help);

        linkEdit = addField(root, "لینک کانفیگ vless://", "");
        linkEdit.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);

        Button parse = new Button(this);
        parse.setText("خواندن لینک");
        parse.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { parseLink(); }
        });
        root.addView(parse);

        hostEdit = addField(root, "هاست", prefs.getString("host", ""));
        portEdit = addField(root, "پورت", String.valueOf(prefs.getInt("port", 443)));
        tokenEdit = addField(root, "TOKEN", prefs.getString("token", ""));
        uuidEdit = addField(root, "UUID", prefs.getString("uuid", ""));

        Button connect = new Button(this);
        connect.setText("وصل شو ✅");
        connect.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { connect(); }
        });
        root.addView(connect);

        Button disconnect = new Button(this);
        disconnect.setText("قطع کن ⏹");
        disconnect.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { disconnect(); }
        });
        root.addView(disconnect);

        status = new TextView(this);
        status.setText("آماده");
        status.setPadding(0, 24, 0, 0);
        root.addView(status);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(root);
        setContentView(scroll);
    }

    private EditText addField(LinearLayout root, String label, String value) {
        TextView tv = new TextView(this);
        tv.setText(label);
        tv.setPadding(0, 16, 0, 0);
        root.addView(tv);
        EditText et = new EditText(this);
        et.setText(value);
        root.addView(et);
        return et;
    }

    private void parseLink() {
        try {
            String link = linkEdit.getText().toString().trim();
            if (!link.startsWith("vless://")) {
                throw new IllegalArgumentException("لینک باید با vless:// شروع شود");
            }
            String rest = link.substring(8);
            int at = rest.indexOf('@');
            if (at < 0) throw new IllegalArgumentException("UUID پیدا نشد");
            String uuid = rest.substring(0, at);
            String after = rest.substring(at + 1);
            int q = after.indexOf('?');
            String authority = q >= 0 ? after.substring(0, q) : after;
            String query = q >= 0 ? after.substring(q + 1) : "";
            int hash = query.indexOf('#');
            if (hash >= 0) query = query.substring(0, hash);

            int colon = authority.lastIndexOf(':');
            String host = colon > 0 ? authority.substring(0, colon) : authority;
            String port = colon > 0 ? authority.substring(colon + 1) : "443";
            String path = "/", security = "tls";
            for (String pair : query.split("&")) {
                int eq = pair.indexOf('=');
                if (eq < 0) continue;
                String k = pair.substring(0, eq);
                String v = URLDecoder.decode(pair.substring(eq + 1), "UTF-8");
                if (k.equals("path")) path = v;
                else if (k.equals("security")) security = v;
            }
            String token = path.startsWith("/") ? path.substring(1) : path;
            if (host.isEmpty() || token.isEmpty()) {
                throw new IllegalArgumentException("هاست یا مسیر خالی است");
            }
            hostEdit.setText(host);
            portEdit.setText(port);
            tokenEdit.setText(token);
            uuidEdit.setText(uuid);
            save();
            status.setText("✅ لینک خوانده شد. حالا «وصل شو» را بزن.");
        } catch (Exception e) {
            Toast.makeText(this, "خطا: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private void save() {
        SharedPreferences.Editor e = prefs.edit();
        e.putString("host", hostEdit.getText().toString().trim());
        e.putString("token", tokenEdit.getText().toString().trim());
        e.putString("uuid", uuidEdit.getText().toString().trim());
        try {
            e.putInt("port", Integer.parseInt(portEdit.getText().toString().trim()));
        } catch (NumberFormatException ex) {
            e.putInt("port", 443);
        }
        String link = linkEdit.getText().toString();
        e.putBoolean("tls", !link.contains("security=none"));
        e.apply();
    }

    private void connect() {
        save();
        if (prefs.getString("host", "").isEmpty() || prefs.getString("token", "").isEmpty()
                || prefs.getString("uuid", "").isEmpty()) {
            Toast.makeText(this, "اول لینک کانفیگ را وارد کن", Toast.LENGTH_LONG).show();
            return;
        }
        Intent prepare = VpnService.prepare(this);
        if (prepare != null) {
            startActivityForResult(prepare, 7);
        } else {
            startVpn();
        }
    }

    private void startVpn() {
        Intent i = new Intent(this, FreeVpnService.class);
        i.setAction(FreeVpnService.ACTION_CONNECT);
        startService(i);
        status.setText("🟢 در حال اتصال… (بار اول ممکنه ۱ دقیقه طول بکشد)");
    }

    private void disconnect() {
        Intent i = new Intent(this, FreeVpnService.class);
        i.setAction(FreeVpnService.ACTION_DISCONNECT);
        startService(i);
        status.setText("⏹ قطع شد");
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == 7) {
            if (resultCode == RESULT_OK) startVpn();
            else status.setText("❌ اجازه VPN داده نشد");
        }
    }
}
