# Stock categories, CRM versus ERP, PO and PI

Received from Neelaj Debnath on 2026-11-12. The meeting date was not stated. The summary below is the original text, unedited. The English digest for all meetings is in [README.md](README.md).

---

ERP-তে stock তিন ভাগে (sample, stock inventory, exhibition) filter করে রাখা হবে, LamiKraft CRM আলাদা থাকবে; leads, samples, PO/PI ও inventory ডেটা এই weekend-এর মধ্যে load করতে হবে।

Stock এর ভাগ

* Stock তিন ভাগে: sample stock, stock inventory, exhibition stock; প্রতিটি থেকে বের করলে plus-minus হিসাব হবে
   * Exhibition stock domestic এবং international warehouse দুটোতেই থাকবে
* Factory তে order দেওয়া work in progress (যেমন 50 বা 200 pieces) ERP তে record ও status সহ দেখাতে হবে
* Netherlands ও US warehouse এর stock জানা থাকতে হবে, যাতে সেখান থেকে যেমন 30 products drop ship করা যায়
* শুধু complete product আসবে; custom products (যেমন রঙ বদলানো riser) আলাদা item হিসেবে থাকবে


CRM বনাম ERP

* Customer ও orders linked থাকবে, তবে CRM পুরো আলাদা section; orders সম্পূর্ণ আলাদা
* Leads CRM ও ERP দুটোতেই যাবে; ERP order processing ও conception থেকে sale পর্যন্ত record রাখার জন্য
* Final leads list LamiKraft CRM এ আছে; Sharman এর কাছে 2-3টা নতুন client বাকি থাকতে পারে


Order flow: PO ও PI

* PO শুধু in-house: Crown (Ahmedabad) কে sheets এর জন্য, Stonecraft কে CNC cutting এর জন্য
   * HBI sheet 1220x244; stock এ থাকলে stock থেকে, নইলে order
* PI (proforma invoice) client কে পাঠানো হয়, selling price এর ভিত্তিতে; client এর PO এর সাথে কোনো সম্পর্ক নেই
* Domestic ও export এর catalog আলাদা, তাই domestic ও export stock আলাদা রাখতে হবে
* চলমান orders (Ida, Lukka) আলাদা; consignment shipment outright purchase নয়, warehouse এ stock হিসেবে থাকে


পরবর্তী পদক্ষেপ

* (Speaker 1) leads, samples, PO/PI ও inventory ডেটা ERP তে load করা, এই weekend এর মধ্যে
* (Speaker 1) PO ও PI বিষয়ে Rajji এর সাথে বসা
* (Speaker 2) পুরো updated leads list দেওয়া, weekend বা সর্বোচ্চ Monday এর মধ্যে; Sharman এর update নেওয়া
* (Speaker 2) Sahil কে তিন স্তরের stock inventory এর কথা জানানো
* (Anirudh) আগামীকাল পুরো updated stock inventory (risers সহ) দেওয়া
* (Francis) Stock inventory ও consignment stock পৌঁছেছে কিনা তার update দেওয়া
* (Priya) Samples এর সম্পূর্ণ Excel, এখন পর্যন্ত সব PO ও PI পাঠানো


গৃহীত সিদ্ধান্ত

* Total stock একসাথে থাকবে, sample, inventory ও exhibition category filter দিয়ে আলাদা করা হবে
* LamiKraft CRM অপরিবর্তিত থাকবে; ERP শুধু processing ও record এর জন্য
