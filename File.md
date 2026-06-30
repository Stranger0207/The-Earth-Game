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
- embargo:oil_trade | AgACAgQAAyEGAATp03G-AAIBp2o-_0xywzH7AXS4ZEkpFuuNA47XAAJ_DWsbGrr5Ue8AAc35mDV3zwEAAwIAA3kAAzwE
- embargo:gas_trade | AgACAgQAAyEGAATp03G-AAIBqGo-_0zvhOx_VoO99jHGchmmfPOEAAKADWsbGrr5UZ-eiTklHo46AQADAgADeAADPAQ
- embargo:steel_trade | AgACAgQAAyEGAATp03G-AAIBqWo-_0_-nIX-Nhbvc3AcndYro6ImAAKBDWsbGrr5Uc1sKnM-eKQUAQADAgADeAADPAQ
- embargo:mineral_trade | AgACAgQAAyEGAATp03G-AAIBqmo-_1ATh5jytzqqoneAjU00R2ttAAKCDWsbGrr5UcwAAXaD6JjvzAEAAwIAA3gAAzwE
- embargo:arms | AgACAgQAAyEGAATp03G-AAIBq2o-_1CDCFeic4VtjM0nUp5Vv44WAAKDDWsbGrr5UWP2whJLTPfSAQADAgADeAADPAQ
- embargo:transport | AgACAgQAAyEGAATp03G-AAIBrGo-_1EdtK5TSq78QHEJp0J16RwnAAKEDWsbGrr5URyJ19GVyM80AQADAgADeAADPAQ
- embargo:diplomatic | AgACAgQAAyEGAATp03G-AAIBr2o-_1fwogYwDOAC0uQvV1GvP3ooAAKFDWsbGrr5UaN8XFCrXoZDAQADAgADeAADPAQ
- wto | AgACAgQAAyEGAATp03G-AAIBsGo-_1kqvdXXRTon04RZ_ddzZk9xAAKGDWsbGrr5UawymD3Kdy10AQADAgADeQADPAQ
- wto | AgACAgQAAyEGAATp03G-AAIBsWo-_1m_VJtXQ-EClOw_55M7TL_PAAKHDWsbGrr5Uagkb3ZxnCPWAQADAgADeAADPAQ
- diplomacy_travel | AgACAgQAAyEGAATp03G-AAIBsmo-_2nispapXk2YcfZEDqfTvnsKAAKIDWsbGrr5UdfbqCAFwzOiAQADAgADdwADPAQ
- diplomacy_travel | AgACAgQAAyEGAATp03G-AAIBs2o-_2pqmR7jAQFcEXqCgmrXxXBzAAKJDWsbGrr5UZMyClAaZ5-kAQADAgADeQADPAQ
- diplomacy_travel | AgACAgQAAyEGAATp03G-AAIBtGo-_2pjbxjA2umOoh3_oY2x9MFnAAKKDWsbGrr5UXNwlYm54S24AQADAgADeAADPAQ
- diplomacy_travel | AgACAgQAAyEGAATp03G-AAIBtWo-_2vmmZHHnLxt17i6i4bZ4mrxAAKLDWsbGrr5Uf8MKanopXtDAQADAgADeAADPAQ
- diplomacy_travel | AgACAgQAAyEGAATp03G-AAIBtmo-_2tMCkpPb0BNZfBKeAj1klpeAAKMDWsbGrr5UV7gRwX4JjvnAQADAgADeQADPAQ
- diplomacy_travel | AgACAgQAAyEGAATp03G-AAIBt2o-_27YQicCYf3AfW8QFFVHNn1hAAKNDWsbGrr5UToU179Z-tFZAQADAgADdwADPAQ
- diplomacy_travel | AgACAgQAAyEGAATp03G-AAIBuGo-_3GDf-CmxLhKRVr06Jso9neCAAKODWsbGrr5UY5ttF1M4RlrAQADAgADdwADPAQ
- diplomacy_travel | AgACAgQAAyEGAATp03G-AAIBuWo-_3KewRwpVtey_JxMdloboU7GAAKPDWsbGrr5UTFT0pxgK6mYAQADAgADeQADPAQ
- meeting | AgACAgQAAyEGAATp03G-AAIBu2o-_3MtWhqRVAXpO8ylP4_hnNccAAKQDWsbGrr5UetmLVZsB2zvAQADAgADeQADPAQ
- meeting | AgACAgQAAyEGAATp03G-AAIBvGo-_3Syeavr8z2s82avNcKx0icFAAKRDWsbGrr5UYThRFVkL5H9AQADAgADdwADPAQ
- meeting | AgACAgQAAyEGAATp03G-AAIBvWo-_3TUCz-aPR9BcMrcAAEWpw8i-QACkg1rGxq6-VGdOpk_xRuv_AEAAwIAA3gAAzwE
- meeting | AgACAgQAAyEGAATp03G-AAIBvmo-_3aWhyxK5elcVRF1bnCoBl56AAKTDWsbGrr5Uays26Jcsz0wAQADAgADdwADPAQ
- meeting | AgACAgQAAyEGAATp03G-AAIBv2o-_3fuIAVOJ6OyNJVQOMMnUy4WAAKUDWsbGrr5Uba65Enzt5fTAQADAgADeAADPAQ
- meeting | AgACAgQAAyEGAATp03G-AAIBwGo-_3mZ3XuCeBvKvVaAUOJUIM13AAKVDWsbGrr5UatFYjcidbCKAQADAgADdwADPAQ
- meeting | AgACAgQAAyEGAATp03G-AAIBwWo-_3mj6778OyePp5YQKlRrIgHuAAKWDWsbGrr5UY8CqkR_ZakjAQADAgADeAADPAQ
- meeting | AgACAgQAAyEGAATp03G-AAIBwmo-_3rOMU-M6YEzr-lQnlUrFG7tAAKXDWsbGrr5UdAi8F7sKMUMAQADAgADeQADPAQ
- wto | 1.jpg | AgACAgQAAyEGAATp03G-AAIVe2pCZsUFlQerlG6hFJElQ_n5Rvd4AAKDDmsbzYUZUrrPon8rsWgIAQADAgADdwADPAQ
- wto | 10.jpg | AgACAgQAAyEGAATp03G-AAIVfGpCZsZFoCjfbPU1rUph2TSBKTAtAAKEDmsbzYUZUpkl0pGQ8Vm1AQADAgADdwADPAQ
- wto | 2.jpg | AgACAgQAAyEGAATp03G-AAIVfWpCZscxU6jpX-W_ciQc58vErb_yAAKFDmsbzYUZUt30ZbT3W0bcAQADAgADeAADPAQ
- wto | 3.jpg | AgACAgQAAyEGAATp03G-AAIVfmpCZsniJrA3YbKn-B7lrYyfHXOsAAKGDmsbzYUZUikpw9OEZWspAQADAgADeQADPAQ
- wto | 4.jpg | AgACAgQAAyEGAATp03G-AAIVf2pCZsrIoH6-WlBwGB89bckx9d_QAAKHDmsbzYUZUvv34CTGZU2yAQADAgADeAADPAQ
- wto | 5.jpg | AgACAgQAAyEGAATp03G-AAIVgGpCZsqSJlJuPq216WHRuZGIBvauAAKIDmsbzYUZUg2qoksSaSDHAQADAgADeQADPAQ
- wto | 6.jpg | AgACAgQAAyEGAATp03G-AAIVgWpCZsss7L9od-DjJQABL7gusecFwAACiQ5rG82FGVJbnTdC4KHzKAEAAwIAA3cAAzwE
- wto | 7.jpg | AgACAgQAAyEGAATp03G-AAIVgmpCZss2iI5on7DmrpVH-IYOQKglAAKKDmsbzYUZUnVya4S5VjgAAQEAAwIAA3gAAzwE
- wto | 8.jpg | AgACAgQAAyEGAATp03G-AAIVg2pCZsyUAVG8N6aj_uLl241EY2ePAAKLDmsbzYUZUlFFr3RNR3G5AQADAgADeQADPAQ
- wto | 9.jpg | AgACAgQAAyEGAATp03G-AAIVhGpCZtBR1IYNhSok-TPP1DVt0oxgAAKMDmsbzYUZUp9xQaUg_ThDAQADAgADeQADPAQ
- trump | 1.jpg | AgACAgQAAyEGAATp03G-AAIVhWpCZtDoupS16wse_YfJkprCbE25AAKNDmsbzYUZUhC9LFraj5ffAQADAgADeQADPAQ
- trump | 2.jpg | AgACAgQAAyEGAATp03G-AAIVhmpCZtE-7FyG1UpHFeLKnsb8YUf-AAKODmsbzYUZUiUItc4lPrjOAQADAgADeAADPAQ
- trump | 3.jpg | AgACAgQAAyEGAATp03G-AAIVh2pCZtEG5nAYLJd7Zr14R2d7kK8PAAKPDmsbzYUZUi5KHp9FXnNPAQADAgADdwADPAQ
- trump | 4.jpg | AgACAgQAAyEGAATp03G-AAIViGpCZtLrw9Nr0De0z_svaZoyNSO_AAKQDmsbzYUZUpn-L2in2yyqAQADAgADdwADPAQ
- trump | 5.jpg | AgACAgQAAyEGAATp03G-AAIViWpCZtYOtvKjnqHXRCYNpM6U_6LNAAKRDmsbzYUZUgXIjVLogwOWAQADAgADeAADPAQ
- diplomacy_travel | 1.jpg | AgACAgQAAyEGAATp03G-AAIVimpCZtZ3GtM0TIIlVH_ViR9rMMhuAAKSDmsbzYUZUiNtwbYe_BgUAQADAgADeAADPAQ
- diplomacy_travel | 10.jpg | AgACAgQAAyEGAATp03G-AAIVi2pCZtfCdWkraI02swRkmUlcrGG2AAKTDmsbzYUZUieea5Z73WBoAQADAgADeQADPAQ
- diplomacy_travel | 2.jpg | AgACAgQAAyEGAATp03G-AAIVjGpCZtwBvmxTTjlfWyUx9UwcMJQrAAKUDmsbzYUZUvXI7u0Wc9LMAQADAgADdwADPAQ
- diplomacy_travel | 3.jpg | AgACAgQAAyEGAATp03G-AAIVjWpCZt0aBzvIxhSRG3ARfyr3QgmDAAKVDmsbzYUZUkiZWsHRw_gYAQADAgADeQADPAQ
- diplomacy_travel | 4.jpg | AgACAgQAAyEGAATp03G-AAIVjmpCZt7QzB5gaHN0z07r4A3R-XsdAAKWDmsbzYUZUn9LUNGQYeuLAQADAgADeAADPAQ
- diplomacy_travel | 5.jpg | AgACAgQAAyEGAATp03G-AAIVj2pCZxjDB6a-h2gMts9tLWGWIWUFAAKXDmsbzYUZUinH0hVXUXcVAQADAgADeAADPAQ
- diplomacy_travel | 6.jpg | AgACAgQAAyEGAATp03G-AAIVkGpCZxkmFIVO6DFILzCJNWKKTI_2AAKYDmsbzYUZUtpX-rZLpeMyAQADAgADeQADPAQ
- diplomacy_travel | 7.jpg | AgACAgQAAyEGAATp03G-AAIVkWpCZxksOzJbzea_woaadnzLyhWgAAKZDmsbzYUZUn_gftnZ4qAlAQADAgADdwADPAQ
- diplomacy_travel | 8.jpg | AgACAgQAAyEGAATp03G-AAIVkmpCZx6wHEoLRkNJTmEY7w2Dc44eAAKaDmsbzYUZUgj2g3xL_0gEAQADAgADdwADPAQ
- diplomacy_travel | 9.jpg | AgACAgQAAyEGAATp03G-AAIVk2pCZx_HtCMJJCb0c0jEv4dq_oUXAAKbDmsbzYUZUvVsfhvr8b1OAQADAgADeQADPAQ
- meeting | 1.jpg | AgACAgQAAyEGAATp03G-AAIVlGpCZyBBVG3cKNoY4Dlm4Wakcd0PAAKcDmsbzYUZUmf4uLia4SuQAQADAgADeQADPAQ
- meeting | 10.jpg | AgACAgQAAyEGAATp03G-AAIVlWpCZyDu6uUjZCfvXK-_-UCAB6_ZAAKdDmsbzYUZUiihB9OQRam7AQADAgADeAADPAQ
- meeting | 2.png | AgACAgQAAyEGAATp03G-AAIVlmpCZyPuAePb0QoJkkImsaPpWXaMAAKeDmsbzYUZUmW57BNE5P7XAQADAgADeQADPAQ
- meeting | 3.jpg | AgACAgQAAyEGAATp03G-AAIVl2pCZyTOiZ3pdFjAo3dZW8rACEpFAAKfDmsbzYUZUs2A3-_QEJvoAQADAgADdwADPAQ
- meeting | 4.jpg | AgACAgQAAyEGAATp03G-AAIVmGpCZyXgFsK_HdEXsLZR2wpHv1UuAAKgDmsbzYUZUiIHTdfz-R35AQADAgADeAADPAQ
- meeting | 5.jpg | AgACAgQAAyEGAATp03G-AAIVmWpCZyh1D0713FJpHsdwaPgOP5QUAAKhDmsbzYUZUizsr8l0-xS5AQADAgADdwADPAQ
- meeting | 6.jpg | AgACAgQAAyEGAATp03G-AAIVmmpCZymo5t6Ztb7DWn5BwCAOasZ6AAKiDmsbzYUZUkA9J7u98DRRAQADAgADeAADPAQ
- meeting | 7.jpg | AgACAgQAAyEGAATp03G-AAIVm2pCZywD3YkKCd4qmrIKIXg-NXEEAAKjDmsbzYUZUmBtH25ulM4jAQADAgADdwADPAQ
- meeting | 8.jpg | AgACAgQAAyEGAATp03G-AAIVnGpCZyzIrFrIhFj3__fvHtrYQq1TAAKkDmsbzYUZUsd2mw0KWvOfAQADAgADeAADPAQ
- meeting | 9.png | AgACAgQAAyEGAATp03G-AAIVnWpCZy1adT1_KcF_IyJET1aNmTxVAAKlDmsbzYUZUhmOMC_bv91uAQADAgADeQADPAQ
