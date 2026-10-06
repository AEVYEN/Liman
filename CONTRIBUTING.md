# Katkıda Bulunma

Liman'a katkı vermek istediğiniz için teşekkürler! Bu belge geliştirme ortamını nasıl kuracağınızı ve değişikliklerinizi nasıl göndereceğinizi anlatır.

## Geliştirme ortamı

En kolay yol her şeyi Docker ile çalıştırmaktır:

```bash
cp .env.example .env
docker compose up -d --build
```

Kod üzerinde hızlı yineleme yapmak için servisleri ayrı ayrı yerelde de çalıştırabilirsiniz.

### API (Python 3.12)

```bash
cd api
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Ayarlar ortam değişkenlerinden ya da `api/.env` dosyasından okunur (bkz. `.env.example`).

### Arayüz (Node.js 22+)

```bash
cd web
npm install
npm run dev
```

Vite geliştirme sunucusu http://localhost:3000 adresinde açılır ve `/v1` ile `/health` isteklerini `http://localhost:8000` adresine yönlendirir. Farklı bir API adresi için `API_URL` ortam değişkenini kullanın.

## Proje yapısı

| Konum | İçerik |
|-------|--------|
| `api/app/engines/` | Çıkarım motorları. Yeni bir motor `Engine` sınıfını (`base.py`) uygular ve `create_engine` içinde seçilir. |
| `api/app/routes/` | HTTP uç noktaları. OpenAI uyumluluğunu bozmamaya dikkat edin. |
| `web/src/App.tsx` | Sohbet arayüzü |
| `web/src/api.ts` | API istemcisi ve SSE akış ayrıştırıcısı |

## Değişiklik gönderme

1. Depoyu fork edin ve `ozellik/kisa-aciklama` ya da `duzeltme/kisa-aciklama` biçiminde bir dal açın.
2. Commit mesajlarında [Conventional Commits](https://www.conventionalcommits.org/tr/) kullanın: `feat:`, `fix:`, `docs:`, `refactor:` …
3. Göndermeden önce şunları kontrol edin:
   - `cd web && npm run build` hatasız tamamlanıyor.
   - `docker compose up -d --build` ile uygulama ayağa kalkıyor ve arayüzden bir sohbet yapılabiliyor.
4. Pull Request açıklamasında neyi neden değiştirdiğinizi ve nasıl test ettiğinizi yazın.

## Hata bildirimi

Issue açarken şunları ekleyin:

- İşletim sistemi, Docker sürümü, CPU mu GPU mu kullanıldığı
- `.env` içindeki `MODEL_ID` ve `MODEL_FILE` değerleri (token'ı **paylaşmayın**)
- `docker compose logs api` çıktısının ilgili kısmı
