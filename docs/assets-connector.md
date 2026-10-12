# Editorial Assets: images from ChatGPT into your book

The second connector, **Editorial Assets** (`https://<domain>/assets/mcp`), takes the images you generate in a ChatGPT conversation and saves them to `EDITORIAL_ROOT/libro/assets/` (`ASSETS_SUBDIR`). From there, the Scribus connector places them.

```
ChatGPT (image generated in the chat, stored in its sandbox at /mnt/data/…)
   │ import_image(image=<file>)       ChatGPT fills {download_url, file_id} (openai/fileParams)
   ▼
gateway /assets/mcp (OAuth, own audience, policy) ─▶ assets server ─▶ download from *.oaiusercontent.com
                                                                       validate → ~/Editorial/libro/assets/x.png
   │ path
   ▼
Scribus connector: create_image_frame + load_image(path) + scale_image_to_frame
```

It's built from our own code (`src/editorial_assets`), runs in its own container, and sits behind the same gateway, OAuth and ngrok. It doesn't use any OpenAI API key, so it costs nothing.

## Tools

| Tool | What it does |
|---|---|
| `import_image(image, name?, folder?)` | ChatGPT hands over the image file (`_meta["openai/fileParams"]`). The server downloads it, validates it and saves it. If the same image arrives twice, it's saved only once (deduplicated by sha256). |
| `list_assets(folder?, limit?)` | Lists the images in the folder, newest first, with absolute path, size and pixels |
| `request_image_upload(name?, folder?)` | Fallback. Returns a **single-use link** (15 min) where you upload the image from the browser or your phone. |

## Connecting it in ChatGPT

Use the same settings as the Scribus connector ([clients.md](clients.md)), changing only:

| Field | Value |
|---|---|
| Name | Editorial Assets |
| Server URL | `https://<domain>/assets/mcp` |

On *Create*, ChatGPT runs its own OAuth flow, with the same consent page and the same owner password. The token it receives is valid **only** for `/assets/mcp`, not for `/mcp`, and vice versa.

## Prompt recipe

> Genera una ilustración de un amplificador de guitarra estilo cuaderno técnico.
> Después guárdala en el editorial con **import_image** (Editorial Assets) con el nombre "amplificador",
> y colócala a página completa en la página 2 del documento abierto en Scribus.

If `import_image` can't receive the file (on ChatGPT web this isn't guaranteed for developer-mode connectors), the model should call `request_image_upload` and give you the link. Download the image from ChatGPT, open the link, upload it, and tell ChatGPT "listo". The model then finds it with `list_assets`.

## Security

| Control | Detail |
|---|---|
| OAuth with its own audience | `aud` is `…/assets/mcp`, so a token for one connector doesn't work on the other |
| Downloads | HTTPS only, hosts in `ASSETS_DOWNLOAD_HOSTS` (`.oaiusercontent.com`, `.openai.com`, `.chatgpt.com`), checked again after every redirect, public IPs only (no SSRF into localhost or the LAN), no cookies or credentials, size capped while streaming (`ASSETS_MAX_BYTES`, 30 MB) |
| Image validation | Magic bytes. Full decode with Pillow, with a pixel cap against decompression bombs. The format must match the magic bytes. **Nothing may follow `IEND`/`EOI`**, which rules out hidden payloads and polyglots. SVG, GIF and anything else is rejected. |
| Provenance | PNG and JPEG are kept **byte for byte**, so the **C2PA** credentials OpenAI embeds survive. `list_assets` and `import_image` report `c2pa: true`. WebP is converted to PNG, because Scribus 1.6 doesn't read it reliably. |
| Writing | Only inside `EDITORIAL_ROOT`, checked twice (gateway path jail and server). Random names, never overwritten, atomic writes, mode 0640. |
| Upload link | Signed with `ASSETS_SECRET`, expires in 15 min, single use. A rejected upload also burns it. Body capped (`ASSETS_MAX_UPLOAD_BYTES`). It's the only route that doesn't go through the bearer check: the token in the URL is the capability. |
| Container | `read_only`, `tmpfs /tmp`, `cap_drop: ALL`, `no-new-privileges`. In host mode it listens on 127.0.0.1:8766. |

## Known limits

- ChatGPT web may not pass the file to a developer-mode connector (`openai/fileParams` is unreliable on web). It did work for Canva in the same conversation. The assets server logs every `import_image` call (`make logs s=assets`), so you can see what arrives.
- The ChatGPT download URL is temporary, so `import_image` has to be called right after generating the image.
