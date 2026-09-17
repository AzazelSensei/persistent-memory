<p align="center"><img src="src/persistent_memory/daemon/static/pm/logo.png" width="140" alt="persistent-memory logo"></p>

# persistent-memory

**AI kodlama ajanları için yerel-öncelikli, incelenebilir hafıza ve çok modelli müzakere.**

Seçilmiş mühendislik kararlarını ve dersleri immutable Markdown olarak saklar, yerel embedding ile getirir ve sonraki ajan oturumlarına sunar. İsteğe bağlı **Council**, tek bir kararı sabit turlarda tartışmak için yapılandırılmış birden fazla ajan CLI'ını çalıştırır; ardından insan incelemesine açık bir öneri kararı yazar.

*English: [README.md](README.md)*

## Nedir?

- Sohbet günlüğü veya kod tabanı RAG'i değil; karar ve ders deposudur.
- `docs/decisions/` ve `docs/lessons/` altında provenance ve supersession bağlantıları taşıyan düz Markdown kayıtlarıdır; eski kayıtlar sessizce değiştirilmez.
- Yerel Ollama `bge-m3` vektör index'ini kuran ve sınırlı recall ekleyen, `127.0.0.1:37778` üzerindeki yerel daemon'dır.
- Yerel daemon için stdio MCP köprüsü; isteğe bağlı hook'lar ve localhost HTTP'dir.
- Makineye özgü bir servistir. Ekipler incelenmiş kayıtları Git ile paylaşır; barındırılan public MCP veya çok kiracılı bir sunucu değildir.

## Yerel-öncelikli, sıfır egress demek değildir

Kayıtlar, vektör index'i ve daemon yerelde kalır. Sistem extraction, recall-aware iş veya Council müzakeresi için kimliği doğrulanmış barındırılan ajan CLI'larını da çalıştırabilir. Bu çağrılar transcript'ten türetilen içeriği, Council konusunu, board mesajlarını ve geri çağrılan kayıtları yapılandırılmış sağlayıcıya gönderebilir. Sağlayıcının abonelik, kota, hız limiti, saklama ve gizlilik şartları geçerlidir. Bu akışları açmadan önce transcript'e veya Council'e izin verdiğiniz içeriği gözden geçirin.

## Nasıl çalışır?

```
Hook / MCP  →  yerel daemon  →  Markdown kayıtları + yerel vektör index'i
                   │                          │
                   ├── sınırlı recall  ←──────┘
                   └── isteğe bağlı Council → öneri karar
```

- **Yakalama:** hook'lar daemon'a sinyal verir; daemon transcript'i dilimler ve eşleşen yapılandırılmış CLI extraction backend'ini çalıştırır. Backend yoksa yakalama atlanır; mevcut kayıtlar aranabilir ve recall edilebilir kalır.
- **Recall:** her prompt'ta anahtar kelime, vektör, güncellik ve önem ağırlıklı hibrit getirme aktif projeye öncelik verir ve en fazla üç kayıt döndürür; diğer projelerden uygun kayıtlar yalnız kullanılmayan yerleri doldurur. 700 tahmini-token bütçesi daha az kayıt üretebilir.
- **Council:** yapılandırılmış üyeler konuya, ilgili recall'a ve append-only board'a erişir. İlk tur bağımsız ve paraleldir; sonraki turlar üyelerin board'a itiraz edebilmesi için sıralı çalışır. Sözcü, insanın kabul veya reddedebileceği `proposed` karar kaydını sentezler.

Council; mimari, trade-off veya ürün yönü gibi bağımsız bakışların değer kattığı önemli sorular içindir. Rutin düzenlemeler veya tek bir kolay doğrulanabilir cevabı olan sorular için uygun değildir. Başarısız ya da atlanmış üyelerle bitebilir; doğru bir uzlaşıyı garanti etmez.

## MCP ve Council

`persistent_memory.mcp_server` bir **stdio** MCP sunucusudur. Varsayılan olarak yalnız yerel daemon ile konuşur; barındırılan bir uç nokta açmaz. Recall sorguları (`search_memory`, `get_record`, `list_recent`, `get_record_provenance`), yerel olarak kimliği doğrulanmış `create_record` ve Council araçlarını (`council_post`, `council_read`, `council_threads`, `council_open`, `council_status`) destekler.

MCP destekli bir istemcide Council açıp durumunu izleyin:

```text
council_open(
  project="my-project",
  topic="Yeni etkinlik akışında cursor pagination kullanmalı mıyız?",
  cwd="/absolute/path/to/my-project",
  rounds=2
)

council_status(project="my-project", session_id="<returned-session-id>")
```

Her proje için aynı anda yalnız bir Council oturumu çalışabilir. Runner her üyenin sonucunu kaydeder ve yalnız üretebildiği durumda nihai sentezi öneri kaydı olarak yazar. Council üyelerinin bu MCP sunucusu üzerinden board'a yazması veya kayıt oluşturması engellenir; yanıtları runner tarafından yakalanır.

`project` parametresi Council board'unu ve oturumunu sınırlar; Council'ın ilk hafıza aramasını **sınırlandırmaz**. Bu arama global hafıza aramasıdır; başka projelerin kayıt kimliklerini, başlıklarını ve proje adlarını döndürebilir. Barındırılan bir Council CLI'ı bu sonuçları konuyla birlikte alabilir; projeler arası metadata'nın yalıtılması gereken bir korpusta Council kullanmayın.

Varsayılanlar projeye uymuyorsa proje köküne `.pm-council.yaml` ekleyin. Aşağıdaki en küçük geçerli örnektir:

```yaml
version: 1
spokesperson: claude
rounds: 2
turn_timeout_seconds: 600
members:
  - id: claude
    backend: claude
    role: "Sistem tasarımı ve uzun vadeli trade-off'lar."
  - id: codex
    backend: codex
    role: "Uygulama gerçekliği ve ölçülebilir maliyet."
  - id: grok
    backend: grok
    role: "Varsayımları kır ve alternatifleri görünür kıl."
```

Desteklenen backend'ler `claude`, `codex`, `kimi` ve `grok`tur. Yapılandırılmış üyeler ve turlar sınırlıdır: en fazla altı üye, beş tur ve sentez dâhil 24 toplam tur çağrısı. Devre dışı veya kullanılamayan üyeler oturum durumunda bildirilir.

## Gereksinimler

- Desteklenen kurulum ve launchd daemon kaydı için macOS.
- Python 3.12 veya üzeri.
- Embedding ve recall için `bge-m3` içeren yerel [Ollama](https://ollama.com).
- Otomatik extraction için eşleşen, kimliği doğrulanmış ajan CLI'ı. Council ayrıca yapılandırılmış her üye CLI'ının kurulu ve kimliği doğrulanmış olmasını ister.

## Hızlı başlangıç

```bash
git clone https://github.com/AzazelSensei/persistent-memory.git
cd persistent-memory
./install.sh
```

Daemon kullanılabilir olduktan sonra demo korpusu deneyin:

```bash
mkdir -p docs
cp -r examples/demo-corpus/decisions examples/demo-corpus/lessons docs/
curl 'http://127.0.0.1:37778/api/search?q=stale+cache+flash+sale'
open http://127.0.0.1:37778
```

Dashboard ve HTTP API `127.0.0.1:37778` üzerinde dinler. Kurulum, desteklenen yerel CLI'larda stdio MCP sürecini kaydeder; MCP sunucusunun yanıt vermesi için yerel daemon yine çalışıyor olmalıdır.

## Doğrulama ve retrieval değerlendirmesi

```bash
./.venv/bin/python -m persistent_memory.doctor --check
./.venv/bin/python -m pytest -q
cp eval/recall_queries.example.json eval/recall_queries.json
./.venv/bin/python eval/recall_eval.py
PM_EVAL_LIVE=1 ./.venv/bin/python -m pytest tests/test_recall_eval_gate.py -q
```

Public repo yalnız başlangıç sorgu setini içerir. Doldurulmuş `eval/recall_queries.json` dosyasını yerelde tutun ve kendi korpusunuza göre uyarlayın; canlı değerlendirme komutları çalışan yerel model ve kayıtlar ister.

## Güvenlik sınırları

- Daemon localhost'a bağlanır; değiştirme uçları yerel bir token kullanır.
- Extraction yolları yapılandırılmış köklere karşı denetlenir; extraction transcript içeriğini talimat değil veri olarak işler.
- Council alt süreçleri, sağlayıcıya özgü sandbox dışı/onay bypass modlarıyla bilinçli olarak başlatılır. `PM_COUNCIL_READONLY=1`, Council üyesi için yalnız bu MCP sunucusunun `create_record` ve `council_post` çağrılarını engeller; işletim sistemi sandbox'ı veya genel bir salt-okunur güvencesi değildir.
- Bunlar uygulama sınırlarıdır, üretim sınıfı izolasyon iddiası değildir. Barındırılan CLI çağrıları yukarıda açıklanan sağlayıcı sınırına tabidir.

## Geliştirme

Kod değiştirmeden önce [AGENTS.md](AGENTS.md) dosyasını okuyun. Mimariyi, kayıtların değişmezlik sözleşmesini, Council yapılandırmasını ve yerel MCP sınırını açıklar.

## Lisans

GNU Affero General Public License v3.0 veya sonrası — bkz. [LICENSE](LICENSE). Bu yazılımı değiştirip ağ servisi olarak çalıştırırsanız, AGPL uyarınca ilgili kaynak kodunu kullanıcılarına sunmalısınız.
