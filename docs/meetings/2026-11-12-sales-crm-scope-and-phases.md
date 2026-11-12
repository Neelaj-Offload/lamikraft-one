# Sales CRM scope and phases

Received from Neelaj Debnath on 2026-11-12. The meeting date was not stated. The summary below is the original text, unedited. The English digest for all meetings is in [README.md](README.md).

---

Sales CRM ke modules (leads, customers, quotations, PI, samples, products, e-commerce stock sync) next Friday tak saare purane data ke saath complete karne hain; production, finance phase two mein.

Customer Page aur Purana Data

* Customer page banega jisme har customer profile ho: jisne kharida ya jise sample gaya, baaki sab leads
   * Customers jaise Luka, Nayla (SRL), aur 'slant train' (naam aisa suna gaya)
* Batch import ya Excel nahi hoga, purana data ek-ek karke daalna hai
* Leads abhi khaali hain kyunki dummy data bharne mein time lag raha tha; full dump pehle bheja ja chuka hai
* Jin parties ko LamiKraft samples gaye, unka record bhi samples mein hona chahiye


Sales Modules ka Scope

* Customers, leads, quotations, proforma invoice bilkul Infiniq process jaise banenge, har quotation customer se attach hogi
* Leads aur customers Priya ke saath, samples Priya aur Priyanka ke saath discuss karne hain; Francis se bhi pooch sakte hain
* Products mein custom products aur catalog products dono daalne hain


Stock Inventory aur E-commerce

* Pehle finished products ka stock inventory add hoga (PRM, BRW, IP nahi), data CRM mein already hai
* Amazon, Flipkart, Pepperfly, website ki sales stock se automatically minus honi chahiye
   * Saare APIs connect karna bada module hai, kaafi time lagega


Aage ke Phases

* Operations mein Raj Ji madad karenge: orders Crown, Kronecraft, Muradabad metal vendor, glass/porcelain vendor se, jo tricky hai
* Finance mein Google ads, Meta ads, website kharche jaise saare cost heads ek jagah aayenge


Agle Kadam

* (Sahil) System host karke team ko dena taaki wo data daalna shuru kar sakein
* (Sahil) Leads, customers, quotations, samples, products aur e-commerce stock module purane data ke saath complete karna, next Friday tak
* (Neelaj Debnath) Custom products aur baaki items ko left side menu mein laana
* (Sab log) Pricing par aapas mein discussion karna


Liye Gaye Faisle

* Production, finance aur website integration phase two mein honge, sales modules ke baad
* Uni commerce (Unicommerce) ki zaroorat nahi rahegi, e-commerce APIs seedhe CRM se judenge
