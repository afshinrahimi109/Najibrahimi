package com.najibrahimi.appfinder;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

/** Search helper that opens Google Play and official publisher search results. */
public class MainActivity extends Activity {
    private static final String PREFS = "app_finder_preferences";
    private static final String LAST_QUERY = "last_query";

    private static final int BACKGROUND = Color.rgb(11, 18, 32);
    private static final int SURFACE = Color.rgb(19, 30, 49);
    private static final int SURFACE_SOFT = Color.rgb(24, 38, 60);
    private static final int TEXT = Color.rgb(241, 247, 255);
    private static final int MUTED = Color.rgb(166, 183, 204);
    private static final int MINT = Color.rgb(57, 214, 175);
    private static final int BLUE = Color.rgb(89, 160, 255);
    private static final int BORDER = Color.rgb(47, 68, 96);

    private EditText searchInput;
    private SharedPreferences preferences;
    private LinearLayout helpDetails;
    private TextView helpToggle;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        preferences = getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        getWindow().setStatusBarColor(BACKGROUND);
        getWindow().setNavigationBarColor(BACKGROUND);

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(BACKGROUND);

        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        page.setPadding(dp(22), dp(24), dp(22), dp(30));
        scroll.addView(page, new ScrollView.LayoutParams(
                ScrollView.LayoutParams.MATCH_PARENT,
                ScrollView.LayoutParams.WRAP_CONTENT));

        buildHeader(page);
        buildSearchCard(page);
        buildOfficialSourcesCard(page);
        buildRegionHelp(page);
        buildPrivacyFooter(page);

        setContentView(scroll);
    }

    private void buildHeader(LinearLayout page) {
        LinearLayout brandRow = new LinearLayout(this);
        brandRow.setGravity(Gravity.CENTER_VERTICAL);
        brandRow.setOrientation(LinearLayout.HORIZONTAL);
        brandRow.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);

        TextView icon = text("⌕", 34, MINT, true);
        icon.setGravity(Gravity.CENTER);
        icon.setBackground(roundRect(SURFACE_SOFT, MINT, 20));
        brandRow.addView(icon, new LinearLayout.LayoutParams(dp(58), dp(58)));

        LinearLayout titleStack = new LinearLayout(this);
        titleStack.setOrientation(LinearLayout.VERTICAL);
        titleStack.setPadding(0, 0, dp(13), 0);
        TextView title = text("راه‌یاب اپ", 25, TEXT, true);
        TextView subtitle = text("مسیر رسمی پیدا کردن برنامه‌ها", 13, MUTED, false);
        titleStack.addView(title);
        titleStack.addView(subtitle);
        brandRow.addView(titleStack, new LinearLayout.LayoutParams(
                0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        page.addView(brandRow);

        TextView badge = text("✓  فقط جست‌وجوی منابع رسمی", 12, MINT, true);
        badge.setGravity(Gravity.CENTER);
        badge.setPadding(dp(13), dp(7), dp(13), dp(7));
        badge.setBackground(roundRect(Color.rgb(16, 55, 54), Color.rgb(35, 116, 99), 40));
        LinearLayout.LayoutParams badgeParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        badgeParams.topMargin = dp(18);
        page.addView(badge, badgeParams);

        TextView intro = text(
                "برنامه را در Google Play پیدا کن؛ اگر در دسترس نبود، راه وب‌سایت سازنده را بررسی کن.",
                15, MUTED, false);
        intro.setLineSpacing(dp(4), 1f);
        LinearLayout.LayoutParams introParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        introParams.topMargin = dp(12);
        page.addView(intro, introParams);
    }

    private void buildSearchCard(LinearLayout page) {
        LinearLayout card = card(page);
        TextView heading = text("دنبال چه برنامه‌ای هستی؟", 18, TEXT, true);
        card.addView(heading);

        TextView hint = text("نام برنامه یا شناسهٔ بسته را بنویس", 13, MUTED, false);
        addTop(card, hint, 6);

        searchInput = new EditText(this);
        searchInput.setSingleLine(true);
        searchInput.setTextDirection(View.TEXT_DIRECTION_FIRST_STRONG);
        searchInput.setGravity(Gravity.CENTER_VERTICAL | Gravity.RIGHT);
        searchInput.setInputType(InputType.TYPE_CLASS_TEXT);
        searchInput.setImeOptions(EditorInfo.IME_ACTION_SEARCH);
        searchInput.setTextColor(TEXT);
        searchInput.setHintTextColor(Color.rgb(116, 137, 163));
        searchInput.setTextSize(15);
        searchInput.setHint("مثلاً واتساپ یا com.example.app");
        searchInput.setPadding(dp(14), dp(12), dp(14), dp(12));
        searchInput.setBackground(roundRect(Color.rgb(13, 23, 39), BORDER, 14));
        searchInput.setText(preferences.getString(LAST_QUERY, ""));
        LinearLayout.LayoutParams inputParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(54));
        inputParams.topMargin = dp(14);
        card.addView(searchInput, inputParams);

        Button playButton = actionButton("جست‌وجو در Google Play", MINT, Color.rgb(7, 34, 34));
        addTop(card, playButton, 12);
        playButton.setOnClickListener(view -> searchPlayStore());
        searchInput.setOnEditorActionListener((view, actionId, event) -> {
            boolean enterPressed = event != null
                    && event.getKeyCode() == KeyEvent.KEYCODE_ENTER
                    && event.getAction() == KeyEvent.ACTION_DOWN;
            if (actionId == EditorInfo.IME_ACTION_SEARCH || enterPressed) {
                searchPlayStore();
                return true;
            }
            return false;
        });

        TextView caption = text(
                "برای شناسه‌هایی مثل com.example.app، صفحهٔ همان برنامه باز می‌شود.",
                12, MUTED, false);
        caption.setLineSpacing(dp(2), 1f);
        addTop(card, caption, 10);
    }

    private void buildOfficialSourcesCard(LinearLayout page) {
        LinearLayout card = card(page);
        TextView heading = text("اگر Play Store در دسترس نبود", 17, TEXT, true);
        card.addView(heading);
        TextView body = text(
                "می‌توانی وب‌سایت رسمی ناشر را پیدا کنی و ببینی آیا خودش نسخهٔ اندروید ارائه می‌دهد.",
                13, MUTED, false);
        body.setLineSpacing(dp(3), 1f);
        addTop(card, body, 7);

        Button websiteButton = actionButton("یافتن وب‌سایت رسمی سازنده", BLUE, Color.rgb(9, 24, 46));
        addTop(card, websiteButton, 13);
        websiteButton.setOnClickListener(view -> searchOfficialWebsite());

        TextView warning = text(
                "نتیجه‌های وب را با دامنهٔ رسمی ناشر بررسی کن؛ این اپ لینک APKهای متفرقه را نمی‌دهد.",
                12, Color.rgb(206, 218, 235), false);
        warning.setLineSpacing(dp(2), 1f);
        addTop(card, warning, 10);
    }

    private void buildRegionHelp(LinearLayout page) {
        LinearLayout card = card(page);
        helpToggle = text("چرا پیام «در کشور شما در دسترس نیست» می‌آید؟  ▾", 14, TEXT, true);
        helpToggle.setGravity(Gravity.RIGHT | Gravity.CENTER_VERTICAL);
        helpToggle.setPadding(0, dp(3), 0, dp(3));
        helpToggle.setOnClickListener(view -> toggleHelp());
        card.addView(helpToggle);

        helpDetails = new LinearLayout(this);
        helpDetails.setOrientation(LinearLayout.VERTICAL);
        helpDetails.setVisibility(View.GONE);
        TextView details = text(
                "این پیام را Google Play یا ناشر برنامه تعیین می‌کند؛ ممکن است برنامه برای منطقه یا دستگاهت عرضه نشده باشد. از صفحهٔ Play Store یا پشتیبانی ناشر پیگیری کن. اگر واقعاً به کشور دیگری نقل‌مکان کرده‌ای، تنظیمات منطقهٔ حساب را فقط طبق راهنمای رسمی Google بررسی کن. این ابزار محدودیت را دور نمی‌زند و فایل نصب دریافت نمی‌کند.",
                13, MUTED, false);
        details.setLineSpacing(dp(4), 1f);
        helpDetails.addView(details);
        LinearLayout.LayoutParams detailsParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        detailsParams.topMargin = dp(12);
        card.addView(helpDetails, detailsParams);
    }

    private void buildPrivacyFooter(LinearLayout page) {
        TextView footer = text(
                "بدون ورود به حساب Google · بدون دسترسی‌های اضافه · آخرین عبارت فقط روی گوشی ذخیره می‌شود",
                11, Color.rgb(126, 147, 174), false);
        footer.setGravity(Gravity.CENTER);
        footer.setLineSpacing(dp(3), 1f);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        params.topMargin = dp(19);
        page.addView(footer, params);
    }

    private void searchPlayStore() {
        String query = currentQuery();
        if (query == null) return;
        rememberQuery(query);
        hideKeyboard();

        String marketUrl;
        String webUrl;
        if (looksLikePackageName(query)) {
            String packageName = Uri.encode(query);
            marketUrl = "market://details?id=" + packageName;
            webUrl = "https://play.google.com/store/apps/details?id=" + packageName;
        } else {
            String encodedQuery = Uri.encode(query);
            marketUrl = "market://search?q=" + encodedQuery + "&c=apps";
            webUrl = "https://play.google.com/store/search?q=" + encodedQuery + "&c=apps";
        }
        openPlayOrWeb(marketUrl, webUrl);
    }

    private void searchOfficialWebsite() {
        String query = currentQuery();
        if (query == null) return;
        rememberQuery(query);
        hideKeyboard();
        String search = query + " official website publisher Android";
        Uri uri = Uri.parse("https://www.google.com/search?q=" + Uri.encode(search));
        openExternal(uri, "مرورگری برای جست‌وجو پیدا نشد.");
    }

    private String currentQuery() {
        String query = searchInput.getText().toString().trim();
        if (query.isEmpty()) {
            searchInput.setError("نام برنامه یا شناسهٔ بسته را وارد کن");
            searchInput.requestFocus();
            Toast.makeText(this, "اول نام برنامه را بنویس.", Toast.LENGTH_SHORT).show();
            return null;
        }
        searchInput.setError(null);
        return query;
    }

    private boolean looksLikePackageName(String query) {
        return query.matches("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z][A-Za-z0-9_]*)+");
    }

    private void openPlayOrWeb(String marketUrl, String webUrl) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(marketUrl)));
        } catch (ActivityNotFoundException notInstalled) {
            openExternal(Uri.parse(webUrl), "Google Play یا مرورگر روی گوشی پیدا نشد.");
        } catch (Exception error) {
            openExternal(Uri.parse(webUrl), "بازکردن لینک Google Play ممکن نشد.");
        }
    }

    private void openExternal(Uri uri, String errorMessage) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (Exception error) {
            Toast.makeText(this, errorMessage, Toast.LENGTH_LONG).show();
        }
    }

    private void rememberQuery(String query) {
        preferences.edit().putString(LAST_QUERY, query).apply();
    }

    private void hideKeyboard() {
        View focused = getCurrentFocus();
        if (focused != null) {
            InputMethodManager manager = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
            if (manager != null) manager.hideSoftInputFromWindow(focused.getWindowToken(), 0);
            focused.clearFocus();
        }
    }

    private void toggleHelp() {
        boolean show = helpDetails.getVisibility() != View.VISIBLE;
        helpDetails.setVisibility(show ? View.VISIBLE : View.GONE);
        helpToggle.setText(show
                ? "چرا پیام «در کشور شما در دسترس نیست» می‌آید؟  ▴"
                : "چرا پیام «در کشور شما در دسترس نیست» می‌آید؟  ▾");
    }

    private LinearLayout card(LinearLayout parent) {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        layout.setPadding(dp(17), dp(17), dp(17), dp(17));
        layout.setBackground(roundRect(SURFACE, BORDER, 20));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        params.topMargin = dp(16);
        parent.addView(layout, params);
        return layout;
    }

    private TextView text(String value, float size, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        view.setGravity(Gravity.RIGHT);
        view.setTextDirection(View.TEXT_DIRECTION_FIRST_STRONG);
        if (bold) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return view;
    }

    private Button actionButton(String label, int backgroundColor, int foregroundColor) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextSize(15);
        button.setTextColor(foregroundColor);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setAllCaps(false);
        button.setMinHeight(dp(52));
        button.setPadding(dp(14), dp(8), dp(14), dp(8));
        button.setBackground(roundRect(backgroundColor, backgroundColor, 14));
        return button;
    }

    private void addTop(LinearLayout parent, View child, int marginDp) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        params.topMargin = dp(marginDp);
        parent.addView(child, params);
    }

    private GradientDrawable roundRect(int fillColor, int strokeColor, int radiusDp) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(fillColor);
        shape.setCornerRadius(dp(radiusDp));
        if (fillColor != strokeColor) shape.setStroke(dp(1), strokeColor);
        return shape;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
