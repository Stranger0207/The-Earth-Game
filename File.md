# File.md — کش عکس‌های اخبار (file_id تلگرام)

این فایل، عکس‌های مورد استفاده‌ی سیستم خبررسانی را به‌صورت `file_id` تلگرام نگه می‌دارد.
اولین بار که هر عکس از فولدر محلی فرستاده می‌شود، تلگرام یک `file_id` دائمی برمی‌گرداند که
اینجا ذخیره می‌شود؛ از آن پس ربات بدون نیاز به روشن‌بودن سیستم محلی (D:\PictureDB) عکس را
از روی همین `file_id` می‌فرستد.

## دسته‌ها و فولدر منبع
- `wto` → `D:\PictureDB\WTO` (اخبار محموله‌ی WTO)
- `trump` → `D:\PictureDB\Trump` (خبر تعرفه در کانال اقتصاد)
- `diplomacy_travel` → `D:\PictureDB\Diplomaci` (خبر سفر دیپلماتیک)
- `meeting` → `D:\PictureDB\Didar` (خبر شروع نشست)
- `embargo` → `D:\PictureDB\Embargo` (خبر تحریم؛ هر عکس مخصوص یک نوع تحریم، کلید کش: `embargo:<نوع>`)

> برای پرکردن یک‌بارهٔ همهٔ عکس‌ها (به‌ویژه ۸ عکس تحریم) روی سیستمی که فولدرهای
> `D:\PictureDB` را دارد، اجرا کن: `PYTHONUTF8=1 python -m scripts.cache_media`
> سپس این فایل را commit و روی VPS `git pull` کن.

## فهرست file_idها
هر خط با فرمت `- دسته | file_id` (به‌صورت خودکار توسط ربات افزوده می‌شود):

- wto | AgACAgQAAyEGAATV9x1nAAMJajzsjrhudpPSXS0WEi8qjzdHQGQAAvIOaxvJtOhR26pNP6wCvFsBAAMCAAN4AAM8BA
- wto | AgACAgQAAyEGAATV9x1nAAMKajzskX2hxlM7FpduE1rU7vWHB3QAAvMOaxvJtOhR1FNppduyKCQBAAMCAAN5AAM8BA
- trump | AgACAgQAAyEGAAMBBMFumAADCWo87NfI6YOG07UGOSI9x2geS_oKAALrDWsb8QboUVgUk-i9kYiCAQADAgADdwADPAQ
- diplomacy_travel | AgACAgQAAyEGAATsbDVoAAMeajztLvd01oEAAZQAAd40KG9aOUq9OwAChw1rG_C46FHp6lB8juwOXwEAAwIAA3kAAzwE
- meeting | AgACAgQAAyEGAATsbDVoAAMfajz33IsBW7faOKzvr4_fqjX9icwAApsNaxvwuOhR20rL0LY44HsBAAMCAAN5AAM8BA
- diplomacy_travel | AgACAgQAAyEGAATsbDVoAAMjaj0OB9VEkL4OiDGjjaPbK6oBnuYAAsINaxvwuOhRz7dZN-ylCCIBAAMCAAN5AAM8BA
- meeting | AgACAgQAAyEGAATsbDVoAAMkaj0eh2JWK-yfp9-CdCe7Lm2KEWAAAtANaxvwuOhRS7mH2JnNW6ABAAMCAAN4AAM8BA
- embargo:financial | AgACAgQAAyEGAATsbDVoAAMmaj0wl6MM_7axkFzFm_js2cVaOgUAAvANaxvwuOhRZVLi8Q8Uo8IBAAMCAAN4AAM8BA
- wto | AgACAgQAAyEGAATV9x1nAAMLaj0yTGer3P-z82qPVoXagULFK4kAAl4PaxvJtOhRmfMB-Tp54a4BAAMCAAN5AAM8BA
