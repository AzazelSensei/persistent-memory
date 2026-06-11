<p align="center"><img src="src/persistent_memory/daemon/static/pm/logo.png" width="140" alt="persistent-memory logo"></p>

# persistent-memory

**AI kodlama ajanları için insan gibi öğrenen kalıcı hafıza — tamamen yerel, ek API key yok.**

Sen sadece geliştirir ve konuşursun. Sistem, ajan konuşmalarından **kararları** (ne seçildi, neden) ve **dersleri** (ne ters gitti, neden, ne zaman) otomatik çıkarır, repo'nun içinde düz markdown olarak saklar ve sonraki session'lara sabit bütçeli bir recall bloğuyla hatırlatır. Hatalar silinmez — üstü çizilir (supersession), gerekçe görünür kalır.

*English documentation: [README.md](README.md)*

## Nedir — ne değildir

**Nedir:**

- **Sohbet kaydı değil, karar beyni.** *Neye karar verdiğini ve nedenini*, *neyin patladığını ve hangi kuralı öğrendiğini* yakalar — ekiplerin session'lar, sprint'ler ve insanlar arasında asıl kaybettiği iki şey bunlardır.
- **Ajanın atıf verebildiği bir denetim izi.** Her kayıt provenance taşır: hangi session, hangi çalışma dizini, hangi ajan — orijinal transcript'ten alıntıyla birlikte.
- **Hatasını kabul eden hafıza.** Yanlış kararlar sessizce yeniden yazılmaz — gerekçeli yeni bir kayıtla üstü çizilir ve eski akıl yürütme okunabilir kalır. Gelecekteki sen sadece güncel cevabı değil, oraya götüren yolu (ve çıkmaz sokakları) da görürsün.
- **Altyapısız.** Bir localhost daemon'ı, bir yerel embedding modeli, repo'nun içinde markdown dosyaları. Hesap yok, bulut yok, API key yok, token faturası yok.

**Ne değildir:**

- ❌ Kod tabanı üzerinde RAG değil — kodun kendisini değil, kod *hakkındaki kararları* hatırlar.
- ❌ Genel amaçlı "her şeyi hatırla" sohbet hafızası değil — bilinçli olarak yalnız karar ve ders çıkarır, çünkü her şey hatırlanmaya değer olunca recall kalitesi ölür.
- ❌ Barındırılan çok-kullanıcılı platform değil — daemon tek makineye hizmet eder; ekipler hafızayı kodu paylaştıkları yolla paylaşır: git.

## Neden barındırılan bir hafıza platformu ya da elle kurulmuş vektör RAG değil?

| | **persistent-memory** | Barındırılan hafıza platformları | Elle kurulan vektör RAG |
|---|---|---|---|
| Verin nerede yaşar | Repo'nda + makinende | Başkasının bulutunda | Kendi altyapında (sen kurarsın) |
| Ne saklanır | Provenance'lı, seçilmiş karar ve dersler | Her şeyin embedding'i/özeti | Neyi chunk'ladıysan |
| Yanıldığında | Üstü çizilir, gerekçe korunur | Üzerine yazılır ya da kopyalanır | Bayat chunk'lar ortalıkta kalır |
| İnsan inceleyebilir mi? | Evet — düz markdown, PR'lanabilir | Nadiren | Pek değil |
| Retrieval kalitesi | Ölçülü: testlerde recall@k / MRR / nDCG tabanlı eval gate | Vendor'a güvenirsin | Ölçersin (hatırlarsan) |
| Maliyet & key'ler | Sıfır — yerel Ollama + mevcut Claude aboneliğin | Abonelik + API key'ler | Embedding API faturası |
| Hangi ajanlarla çalışır | Claude Code, Codex CLI, her MCP istemcisi, düz `curl` | SDK'ya bağımlı | Ne bağlarsan |

Dürüst trade-off: barındırılan platformlar cihazlar arası senkronu ve çok kullanıcılı panelleri hazır verir. Bu proje diğer tarafı seçer — mühendislik kararların makinenden hiç çıkmaz ve hafızanın kendisi opak bir veritabanı yerine repo'nda incelenebilir bir artefakttır.

## Ekipler için (başka bir sunucuyla değil, git'le)

Kayıtlar repo'nun içinde düz markdown olduğu için:

- **Karar tarihçesi kodla birlikte taşınır.** Repo'yu klonlayan herkese her "bu neden böyle yapılmış" sorusunun cevabı da gelir — GitHub'da insan okur, ekip arkadaşının ajan session'larına otomatik enjekte edilir.
- **Hafıza code review'dan geçer.** Kayıtlar PR'larla gelebilir; bir ekip arkadaşı bir karar kaydına, koda itiraz ettiği gibi itiraz edebilir.
- **Onboarding kısalır.** Yeni geliştirici (ya da yepyeni bir AI session'ı) ekibe yeniden sormak yerine karar/ders tarihçesini okur — recall hook'u bunu zaten otomatik yapar.
- **Dersler tekrarlanmaz.** "Bunu ocakta denedik, orders tablosunu kilitledi" ikinci denemeden *önce*, orijinal olayın bağlantısıyla ortaya çıkar.
- **Ajan kilidi yok.** Bir ekip arkadaşı Claude Code'da, diğeri Codex'te, üçüncüsü `curl` ile script'te — aynı hafıza, üç erişim yolu.

## İlkeler

- **Kararlar sorgulanır, hatalar silinmez** — kayıtlar immutable; düzeltme supersession bağıyla yapılır, akıl yürütme tarihçesi kaybolmaz.
- **Tamamen yerel, sıfır egress** — embedding yerel Ollama modelinden gelir; makineden hiçbir şey çıkmaz.
- **Kalite > token** — recall sabit token bütçesiyle, aktif projeye scope'lu enjekte edilir; çapraz-proje kayıtlar yalnız benzerlik eşiğini geçince harmanlanır.
- **Düz markdown tek gerçek kaynak** — kayıtlar `docs/decisions/` ve `docs/lessons/` altında yaşar, git'e commit'lenebilir; bir insan (ya da başka bir ajan) projenin karar tarihçesini doğrudan GitHub'dan okuyabilir.

## Nasıl çalışır

```
Hook'lar (sinyal)  →  Daemon (FastAPI, 127.0.0.1:37778)  →  Kayıtlar (docs/decisions, docs/lessons)
                          │                                      │
                          │                              Vektör index (Ollama bge-m3, numpy)
                          │                                      │
                          └── Recall enjeksiyonu  ←  Hibrit retrieval (BM25 + vektör + recency + salience, RRF)
```

- **Yakalama:** hafif hook'lar her N mesajda ve session sonunda tetiklenir; daemon transcript'in yeni kısmını dilimleyip headless `claude -p` extraction worker'ı başlatır (mevcut Claude aboneliğinle çalışır — API key gerekmez).
- **Index:** kayıtlar yerel Ollama `bge-m3` ile (1024 boyut, güçlü TR/EN köprüsü) content-hash tazeliğiyle numpy vektör index'ine gömülür.
- **Recall:** session başında ve her prompt'ta daemon en alakalı kayıtları getirir (BM25 + vektör hibrit, RRF füzyonu, recency ve salience ağırlıklı) ve kompakt bir hafıza bloğu enjekte eder.
- **Konsolidasyon:** opsiyonel graf geçişi kayıtları topluluklara kümeler ve supersession adayları önerir; dashboard'dan incelenir.

## Her ajanın kullanabileceği üç yol

1. **Hook'lar (otomatik)** — Claude Code ve Codex CLI aynı hook kontratını paylaşır; `install.sh` ikisini de kaydeder. Recall ve extraction kendiliğinden çalışır.
2. **MCP (pull)** — read-only MCP server görev ortasında sorgu için `search_memory`, `get_record`, `list_recent`, `get_record_provenance` araçlarını sunar.
3. **Düz HTTP** — herhangi bir ajan ya da script localhost API'sine erişebilir:
   ```bash
   curl 'http://127.0.0.1:37778/api/search?q=cache+invalidation&top_k=5'
   curl 'http://127.0.0.1:37778/api/recall?project=projem'
   ```
   Yazma uçları `X-PM-Token` header'ı ister (token dosyası: `docs/.pm-index/daemon.token`).

## Gereksinimler

- macOS (daemon launchd altında çalışır; kod taşınabilir ama installer macOS'a özgü)
- Python ≥ 3.12
- [Ollama](https://ollama.com) + `bge-m3` modeli (preflight doctor eksikleri kendisi kurar)
- Extraction worker için Claude Code CLI — yoksa yakalama kapalı kalır ama arama/recall çalışmaya devam eder (degraded mod)

## Hızlı başlangıç

```bash
git clone https://github.com/AzazelSensei/persistent-memory.git
cd persistent-memory
./install.sh            # doctor preflight + venv + hook'lar + launchd daemon
```

Demo korpusla hemen dene:

```bash
cp -r examples/demo-corpus/decisions examples/demo-corpus/lessons docs/
curl 'http://127.0.0.1:37778/api/search?q=stale+cache+flash+sale'
open http://127.0.0.1:37778        # dashboard
```

> **Dashboard adresi:** her zaman `http://127.0.0.1:37778` — port **sabittir** (37778) ve daemon yalnız localhost'a bağlanır. Portsuz `http://127.0.0.1` açmak hiçbir şey yüklemez.

Faydalı komutlar:

```bash
./.venv/bin/python -m pytest -q                      # test paketi
./.venv/bin/python -m persistent_memory.doctor --check   # önkoşul taraması
./.venv/bin/python -m persistent_memory.daemon       # daemon'ı elle çalıştır
./.venv/bin/python eval/recall_eval.py               # retrieval kalite benchmark'ı
scripts/backup.sh docs my-snapshot.tar.gz            # kayıt + index snapshot'ı
```

## Retrieval kalitesini ölçmek

`eval/recall_eval.py` bir sorgu seti üzerinden recall@k, MRR, nDCG@10 ve latency ölçer (`eval/recall_queries.json` gitignore'ludur — `eval/recall_queries.example.json`'dan başlayıp kendi kaçırılan sorgularınla büyüt). Canlı regresyon gate'i (`PM_EVAL_LIVE=1 pytest tests/test_recall_eval_gate.py`) retrieval kalitesi ölçülmüş tabanların altına düşünce kırılır — retrieval'a dokunan her değişiklikten önce çalıştır.

## Güvenlik modeli

- Daemon yalnız `127.0.0.1`'e bağlanır; yazma uçları sabit-zamanlı karşılaştırılan token ister.
- Extraction worker'a giden transcript ve çalışma-dizini yolları izinli kök listesine karşı doğrulanır.
- Extraction prompt'u transcript içeriğini kesinlikle veri olarak işler — transcript içindeki talimatlar asla yürütülmez.

## AI ajanlarıyla geliştirme

Bu proje neredeyse tamamen talimat dosyalarından çalışan AI ajanlarıyla geliştirildi ve aynı şekilde genişletilmek üzere tasarlandı. [`AGENTS.md`](AGENTS.md) ajana dönük el kitabıdır: mimari harita, doğrulanmış komutlar, katı kurallar (TDD, eval gate'leri, immutability kontratları) ve bilinen tuzaklar. Değişiklik istemeden önce ajanını oraya yönlendir.

## Lisans

GNU Affero General Public License v3.0 veya sonrası — bkz. [LICENSE](LICENSE).

Bu proje AGPL-3.0-or-later ile lisanslanmıştır. Bu yazılımı değiştirip bir ağ servisi olarak çalıştırırsanız, değiştirilmiş sürümünüzün eksiksiz kaynak kodunu o servisin kullanıcılarına sunmak zorundasınız.
