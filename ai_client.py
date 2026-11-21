"""عميل API متوافق مع OpenAI: محادثة، جلب النماذج، صور، فيديو."""
import asyncio
import base64
import time

import httpx

import config


class AIError(Exception):
    """خطأ يُعرض للمستخدم برسالة عربية ودية."""


class AIClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self._http = httpx.AsyncClient(timeout=config.AI_TIMEOUT)

    # ---------- أدوات داخلية ----------

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _raise_for(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        message = ""
        try:
            data = response.json()
            error = data.get("error") if isinstance(data, dict) else None
            if isinstance(error, dict):
                message = error.get("message", "")
            elif isinstance(data, dict):
                message = data.get("message", "") or ""
        except Exception:
            pass
        hints = {
            401: "المفتاح غير صحيح أو منتهي الصلاحية.",
            403: "المفتاح لا يملك صلاحية الوصول إلى هذا النموذج.",
            404: "الرابط غير صحيح أو المسار غير موجود.",
            429: "تم تجاوز حد الطلبات، حاول بعد قليل.",
            500: "خطأ داخلي في خادم النموذج.",
        }
        text = hints.get(response.status_code, f"خطأ {response.status_code}")
        if message:
            text += f" ({message})"
        raise AIError(text)

    async def _post(self, path: str, payload: dict):
        try:
            response = await self._http.post(
                self.base_url + path, json=payload, headers=self._headers()
            )
        except httpx.TimeoutException:
            raise AIError("انتهت مهلة الطلب إلى الخادم.")
        except httpx.RequestError:
            raise AIError("تعذّر الاتصال بالخادم، تحقق من الرابط.")
        self._raise_for(response)
        try:
            return response.json()
        except Exception:
            raise AIError("استجابة غير متوقعة من الخادم.")

    async def _get(self, path: str):
        try:
            response = await self._http.get(
                self.base_url + path, headers=self._headers()
            )
        except httpx.TimeoutException:
            raise AIError("انتهت مهلة الطلب إلى الخادم.")
        except httpx.RequestError:
            raise AIError("تعذّر الاتصال بالخادم، تحقق من الرابط.")
        self._raise_for(response)
        try:
            return response.json()
        except Exception:
            raise AIError("استجابة غير متوقعة من الخادم.")

    async def _download(self, url: str) -> bytes:
        try:
            response = await self._http.get(url)
        except httpx.RequestError:
            raise AIError("تعذّر تنزيل الملف من الرابط.")
        self._raise_for(response)
        return response.content

    # ---------- النماذج ----------

    async def list_models(self) -> list:
        data = await self._get("/models")
        items = data.get("data") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise AIError("استجابة غير متوقعة من الخادم.")
        model_ids = []
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                model_ids.append(str(item["id"]))
            elif isinstance(item, str):
                model_ids.append(item)
        return model_ids

    # ---------- المحادثة (نص + صور) ----------

    async def chat(self, model: str, messages: list, temperature: float = 0.7) -> str:
        data = await self._post(
            "/chat/completions",
            {"model": model, "messages": messages, "temperature": temperature},
        )
        try:
            content = data["choices"][0]["message"]["content"]
            if content:
                return content
        except (KeyError, IndexError, TypeError):
            pass
        if isinstance(data, dict):
            for key in ("response", "text", "content"):
                if data.get(key):
                    return str(data[key])
        raise AIError("استجابة غير متوقعة من نموذج المحادثة.")

    # ---------- الصور ----------

    async def generate_image(self, model: str, prompt: str, size: str = "1024x1024") -> bytes:
        data = await self._post(
            "/images/generations",
            {"model": model, "prompt": prompt, "size": size, "n": 1},
        )
        items = data.get("data") or []
        if not items:
            raise AIError("لم يرجع الخادم أي صورة.")
        item = items[0]
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        if item.get("url"):
            return await self._download(item["url"])
        raise AIError("استجابة الصورة غير متوقعة.")

    # ---------- الفيديو ----------

    @staticmethod
    def _extract_video_url(job: dict):
        if not isinstance(job, dict):
            return None
        for key in ("url", "video_url", "output_url", "result_url"):
            if job.get(key):
                return job[key]
        result = job.get("result") or job.get("data") or job.get("output")
        if isinstance(result, dict):
            for key in ("url", "video_url"):
                if result.get(key):
                    return result[key]
        return None

    async def generate_video(self, model: str, prompt: str, timeout: int = 600) -> bytes:
        payload = {"model": model, "prompt": prompt}
        job = None
        last_status = None
        for path in ("/videos/generations", "/videos"):
            try:
                response = await self._http.post(
                    self.base_url + path, json=payload, headers=self._headers()
                )
                if response.status_code in (200, 201, 202):
                    job = response.json()
                    break
                last_status = response.status_code
            except httpx.RequestError:
                last_status = None
        if job is None:
            if last_status == 404:
                raise AIError(
                    "خادم الفيديو غير مدعوم على هذا الرابط (404). "
                    "تأكد أن الرابط يدعم إنشاء الفيديو وأن النموذج صحيح."
                )
            raise AIError("تعذّر بدء إنشاء الفيديو على الخادم.")

        url = self._extract_video_url(job)
        if url:
            return await self._download(url)

        job_id = None
        if isinstance(job, dict):
            job_id = job.get("id") or job.get("job_id") or job.get("request_id")
        if not job_id:
            raise AIError("استجابة غير متوقعة من خادم الفيديو.")

        deadline = time.time() + timeout
        while time.time() < deadline:
            await asyncio.sleep(5)
            data = None
            for path in (f"/videos/{job_id}", f"/videos/generations/{job_id}"):
                try:
                    response = await self._http.get(
                        self.base_url + path, headers=self._headers()
                    )
                    if response.status_code == 200:
                        data = response.json()
                        break
                except httpx.RequestError:
                    continue
            if data is None:
                continue
            status = str(data.get("status", "")).lower()
            if status in ("completed", "succeeded", "success", "done", "finished"):
                url = self._extract_video_url(data)
                if url:
                    return await self._download(url)
                # بعض الواجهات تُنزّل الفيديو من /videos/{id}/content
                try:
                    response = await self._http.get(
                        self.base_url + f"/videos/{job_id}/content",
                        headers=self._headers(),
                    )
                    if response.status_code == 200 and response.content:
                        return response.content
                except httpx.RequestError:
                    pass
                raise AIError("اكتمل الفيديو لكن لم يتم العثور على رابطه.")
            if status in ("failed", "error", "cancelled", "canceled"):
                detail = data.get("error") or data.get("message") or status
                raise AIError(f"فشل إنشاء الفيديو: {detail}")
        raise AIError("انتهت مهلة إنشاء الفيديو (10 دقائق).")
