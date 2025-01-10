import asyncio
import aiohttp

from director.utils.asyncio import is_event_loop_running

PARAMS_CONFIG = {
    "text_to_video": {
        "model_name": {
            "type": "string",
            "description": "The model name to use for video generation",
            "default": "fal-ai/fast-animatediff/text-to-video",
            "enum": [
                "fal-ai/minimax-video",
                "fal-ai/mochi-v1",
                "fal-ai/hunyuan-video",
                "fal-ai/luma-dream-machine",
                "fal-ai/kling-video/v1/standard/text-to-video",
                "fal-ai/kling-video/v1.5/pro/text-to-video",
                "fal-ai/cogvideox-5b",
                "fal-ai/ltx-video",
                "fal-ai/fast-svd/text-to-video",
                "fal-ai/fast-svd-lcm/text-to-video",
                "fal-ai/t2v-turbo",
                "fal-ai/fast-animatediff/text-to-video",
                "fal-ai/fast-animatediff/turbo/text-to-video",
                # "fal-ai/animatediff-sparsectrl-lcm",
            ],
        },
    },
    "image_to_image": {
        "model_name": {
            "type": "string",
            "description": "The model name to use for image-to-image transformation",
            "default": "fal-ai/flux-lora-canny",
            "enum": [
                "fal-ai/flux-pro/v1.1-ultra/redux",
                "fal-ai/flux-lora-canny",
                "fal-ai/flux-lora-depth",
                "fal-ai/ideogram/v2/turbo/remix",
                "fal-ai/iclight-v2",
            ],
        },
    },
}


class FalVideoGenerationTool:
    def __init__(self, api_key: str):
        if not api_key:
            raise Exception("FAL API key not found")
        self.api_key = api_key
        self.queue_endpoint = "https://queue.fal.run"
        self.polling_interval = 10  # seconds

    async def text_to_video_async(
        self, prompt: str, save_at: str, duration: float, config: dict
    ):
        """
        Generates a video asynchronously by calling the Fal text-to-video API using aiohttp.
        """
        try:
            model_name = config.get(
                "model_name", "fal-ai/fast-animatediff/text-to-video"
            )

            headers = {"authorization": f"Key {self.api_key}"}
            fal_queue_payload = {"prompt": prompt, "duration": duration}
            fal_queue_endpoint = f"{self.queue_endpoint}/{model_name}"

            async with aiohttp.ClientSession() as session:
                # Submit job to Fal queue
                fal_response = await session.post(
                    fal_queue_endpoint, headers=headers, json=fal_queue_payload
                )
                fal_response_json = await fal_response.json()

                if (
                    "status_url" not in fal_response_json
                    or "response_url" not in fal_response_json
                ):
                    raise ValueError(
                        f"Invalid response from FAL queue: Missing 'status_url' or 'response_url'. Response: {fal_response_json}"
                    )

                status_url = fal_response_json["status_url"]
                response_url = fal_response_json["response_url"]

                # Poll for status
                while True:
                    status_response = await session.get(status_url, headers=headers)
                    status_json = await status_response.json()

                    if "status" not in status_json:
                        raise ValueError(
                            f"Invalid response from FAL queue: Missing 'status'. Response: {status_json}"
                        )

                    if status_json["status"] in ["IN_QUEUE", "IN_PROGRESS"]:
                        await asyncio.sleep(self.polling_interval)
                        continue
                    elif status_json["status"] == "COMPLETED":
                        # Fetch results
                        response = await session.get(response_url, headers=headers)
                        res = await response.json()

                        video_url = res["video"]["url"]

                        # Download the video
                        async with session.get(video_url) as video_response:
                            with open(save_at, "wb") as f:
                                f.write(await video_response.read())
                        break
                    else:
                        raise ValueError(
                            f"Unknown status for FAL request: {status_json}"
                        )

        except Exception as e:
            raise Exception(f"Error generating video: {str(e)}")

        return {"status": "success", "video_path": save_at}

    def text_to_video(self, *args, **kwargs):
        """
        Blocking call to generate video (synchronous wrapper around the async method).
        """
        is_loop_running = is_event_loop_running()
        if not is_loop_running:
            return asyncio.run(self.text_to_video_async(*args, **kwargs))
        else:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.text_to_video_async(*args, **kwargs))

    async def image_to_image_async(self, image_url: str, save_at: str, prompt: str, config: dict):
        """
        Asynchronous method for generating an image using the FAL image-to-image API.
        """
        try:
            if not image_url or not save_at:
                raise ValueError("image_url and save_at are required parameters")
            if not prompt:
                raise ValueError("prompt is a required parameter")

            model_name = config.get("model_name", "fal-ai/flux-lora-canny")

            headers = {"authorization": f"Key {self.api_key}"}
            fal_queue_payload = {"image_url": image_url, "prompt": prompt}
            fal_queue_endpoint = f"{self.queue_endpoint}/{model_name}"

            async with aiohttp.ClientSession() as session:
                fal_response = await session.post(
                    fal_queue_endpoint, headers=headers, json=fal_queue_payload
                )
                fal_response.raise_for_status()
                fal_response_json = await fal_response.json()

                if "status_url" not in fal_response_json or "response_url" not in fal_response_json:
                    raise ValueError(
                        f"Invalid response from FAL queue: Missing 'status_url' or 'response_url'. Response: {fal_response_json}"
                    )

                status_url = fal_response_json["status_url"]
                response_url = fal_response_json["response_url"]

                max_retries = 30  # 5 minutes with 10-second intervals
                retry_count = 0
                while True:
                    if retry_count >= max_retries:
                        raise TimeoutError("FAL API request timed out after 5 minutes")

                    status_response = await session.get(status_url, headers=headers)
                    status_json = await status_response.json()

                    if status_json["status"] in ["IN_QUEUE", "IN_PROGRESS"]:
                        await asyncio.sleep(self.polling_interval)
                        retry_count += 1
                        continue
                    elif status_json["status"] == "COMPLETED":
                        response = await session.get(response_url, headers=headers)
                        res = await response.json()

                        if not res.get("images"):
                            raise Exception("No images returned in FAL response.")
                        elif not res["images"]:
                           raise Exception("Empty images list in FAL response.")

                        image_url_result = res["images"][0]["url"]

                        async with session.get(image_url_result) as image_response:
                            with open(save_at, "wb") as f:
                                f.write(await image_response.read())
                        break
                    else:
                        raise ValueError(f"Unknown status for FAL request: {status_json}")

        except Exception as e:
            raise Exception(f"Error generating image: {str(e)}") from e

        return {"status": "success", "image_url": image_url_result, "image_path": save_at}

    def image_to_image(self, *args, **kwargs):
        """
        Blocking call to generate image (synchronous wrapper around the async method).
        """
        is_loop_running = is_event_loop_running()
        if not is_loop_running:
            return asyncio.run(self.image_to_image_async(*args, **kwargs))
        else:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.image_to_image_async(*args, **kwargs))
