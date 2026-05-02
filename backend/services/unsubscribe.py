import asyncio
import base64
import json
import logging
from typing import AsyncGenerator

from backend.config import get_settings
from backend.services.ai_models import (
    CU_CONFIG,
    DEFAULT_CU_MODEL,
    base_model_id,
    is_fast_variant,
)

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_CU_ITERATIONS = 12
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 900
NAV_TIMEOUT_MS = 20000

# Structured tool the model calls to report the unsubscribe outcome instead
# of relying on English-keyword detection in its final text. This works for
# non-English unsubscribe pages too and lets us short-circuit the loop the
# moment the model is confident.
UNSUBSCRIBE_STATUS_TOOL = {
    "name": "report_unsubscribe_status",
    "description": (
        "Report the final outcome of the unsubscribe attempt. Call this as "
        "your VERY LAST action when the unsubscribe is complete or you have "
        "decided to stop. Do not call any other tools after this."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["success", "failure", "needs_human"],
                "description": (
                    "success = the page confirmed the user is unsubscribed; "
                    "needs_human = blocked by CAPTCHA / login wall / similar; "
                    "failure = could not complete the unsubscribe."
                ),
            },
            "reason": {
                "type": "string",
                "description": "Short human-readable explanation of the outcome.",
            },
        },
        "required": ["status", "reason"],
    },
}


def _encode_screenshot(png_bytes: bytes) -> str:
    return base64.b64encode(png_bytes).decode("ascii")


def _make_thumbnail(png_bytes: bytes, max_width: int = 640) -> bytes:
    """Downscale screenshot PNG for SSE streaming to the frontend."""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(png_bytes))
        if img.width > max_width:
            ratio = max_width / img.width
            new_size = (max_width, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except ImportError:
        return png_bytes


class UnsubscribeEvent:
    """A single progress event sent to the SSE stream."""

    def __init__(self, step: str, message: str, screenshot_b64: str = None,
                 llm_reasoning: str = None, status: str = "in_progress",
                 error: str = None):
        self.step = step
        self.message = message
        self.screenshot_b64 = screenshot_b64
        self.llm_reasoning = llm_reasoning
        self.status = status
        self.error = error

    def to_dict(self) -> dict:
        d = {
            "step": self.step,
            "message": self.message,
            "status": self.status,
        }
        if self.screenshot_b64:
            d["screenshot"] = self.screenshot_b64
        if self.llm_reasoning:
            d["llm_reasoning"] = self.llm_reasoning
        if self.error:
            d["error"] = self.error
        return d


class UnsubscribeService:
    def __init__(self, model: str = None):
        self._anthropic_client = None
        requested = model or DEFAULT_CU_MODEL
        # Computer Use is incompatible with fast-mode; strip the suffix and
        # fall back to the model's normal CU config.
        self.model = base_model_id(requested)
        self._used_fast_request = is_fast_variant(requested)
        cu_entry = CU_CONFIG.get(self.model) or CU_CONFIG.get(requested)
        if not cu_entry:
            cu_entry = CU_CONFIG[DEFAULT_CU_MODEL]
            self.model = DEFAULT_CU_MODEL
        self.cu_beta, self.cu_tool_type = cu_entry

    def _get_anthropic(self):
        if self._anthropic_client is None:
            import anthropic
            api_key = settings.claude_api_key
            if not api_key:
                raise ValueError("Claude API key not configured")
            self._anthropic_client = anthropic.Anthropic(api_key=api_key)
        return self._anthropic_client

    async def _take_screenshot(self, page) -> tuple[bytes, str, str]:
        """Take a screenshot and return (full_png, full_b64, thumbnail_b64)."""
        png_bytes = await page.screenshot(type="png")
        full_b64 = _encode_screenshot(png_bytes)
        thumb_b64 = _encode_screenshot(_make_thumbnail(png_bytes))
        return png_bytes, full_b64, thumb_b64

    async def _execute_computer_action(self, page, tool_input: dict) -> str:
        """Execute a computer use action via Playwright. Returns description of what was done."""
        action = tool_input.get("action")
        coord = tool_input.get("coordinate")

        if action in ("left_click", "click"):
            if coord:
                await page.mouse.click(coord[0], coord[1])
                return f"Clicked at ({coord[0]}, {coord[1]})"
            return "Click requested but no coordinate provided"

        elif action == "double_click":
            if coord:
                await page.mouse.dblclick(coord[0], coord[1])
                return f"Double-clicked at ({coord[0]}, {coord[1]})"
            return "Double-click requested but no coordinate provided"

        elif action == "right_click":
            if coord:
                await page.mouse.click(coord[0], coord[1], button="right")
                return f"Right-clicked at ({coord[0]}, {coord[1]})"
            return "Right-click requested but no coordinate provided"

        elif action == "mouse_move":
            if coord:
                await page.mouse.move(coord[0], coord[1])
                return f"Moved mouse to ({coord[0]}, {coord[1]})"
            return "Mouse move requested but no coordinate provided"

        elif action == "type":
            text = tool_input.get("text", "")
            await page.keyboard.type(text, delay=30)
            return f"Typed: {text[:50]}{'...' if len(text) > 50 else ''}"

        elif action == "key":
            key_combo = tool_input.get("text", "")
            # Translate common key names to Playwright format
            key_map = {
                "Return": "Enter",
                "return": "Enter",
                "space": " ",
                "Space": " ",
                "BackSpace": "Backspace",
            }
            mapped = key_map.get(key_combo, key_combo)
            # Handle combos like "ctrl+a"
            if "+" in mapped:
                parts = mapped.split("+")
                for p in parts[:-1]:
                    await page.keyboard.down(p.strip())
                await page.keyboard.press(parts[-1].strip())
                for p in reversed(parts[:-1]):
                    await page.keyboard.up(p.strip())
            else:
                await page.keyboard.press(mapped)
            return f"Pressed key: {key_combo}"

        elif action == "scroll":
            if coord:
                delta = tool_input.get("delta", [0, -3])
                scroll_x = delta[0] * 100 if isinstance(delta, list) and len(delta) > 0 else 0
                scroll_y = delta[1] * 100 if isinstance(delta, list) and len(delta) > 1 else -300
                await page.mouse.move(coord[0], coord[1])
                await page.mouse.wheel(scroll_x, scroll_y)
                return f"Scrolled at ({coord[0]}, {coord[1]})"
            await page.mouse.wheel(0, -300)
            return "Scrolled down"

        elif action == "screenshot":
            return "screenshot_requested"

        elif action == "cursor_position":
            return "cursor_position_requested"

        elif action == "left_click_drag":
            start = coord
            end = tool_input.get("end_coordinate", coord)
            if start and end:
                await page.mouse.move(start[0], start[1])
                await page.mouse.down()
                await page.mouse.move(end[0], end[1])
                await page.mouse.up()
                return f"Dragged from ({start[0]}, {start[1]}) to ({end[0]}, {end[1]})"
            return "Drag requested but coordinates incomplete"

        elif action == "triple_click":
            if coord:
                await page.mouse.click(coord[0], coord[1], click_count=3)
                return f"Triple-clicked at ({coord[0]}, {coord[1]})"
            return "Triple-click requested but no coordinate provided"

        elif action == "wait":
            duration = tool_input.get("duration", 2)
            await page.wait_for_timeout(min(duration, 5) * 1000)
            return f"Waited {duration}s"

        return f"Unknown action: {action}"

    async def unsubscribe_via_url(
        self,
        url: str,
        user_email: str,
    ) -> AsyncGenerator[UnsubscribeEvent, None]:
        """Use Playwright + Claude Computer Use to navigate an unsubscribe URL."""
        from playwright.async_api import async_playwright

        yield UnsubscribeEvent(step="starting", message="Launching browser...")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            try:
                yield UnsubscribeEvent(step="navigating", message="Loading unsubscribe page...")

                await page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                # Take initial screenshot
                _, full_b64, thumb_b64 = await self._take_screenshot(page)

                yield UnsubscribeEvent(
                    step="analyzing_1",
                    message="AI is analyzing the page...",
                    screenshot_b64=thumb_b64,
                )

                # Build the initial Computer Use conversation
                client = self._get_anthropic()
                tools = [
                    {
                        "type": self.cu_tool_type,
                        "name": "computer",
                        "display_width_px": VIEWPORT_WIDTH,
                        "display_height_px": VIEWPORT_HEIGHT,
                        "display_number": 1,
                    },
                    UNSUBSCRIBE_STATUS_TOOL,
                ]

                system_prompt = (
                    "You are an expert at unsubscribing from email mailing lists. "
                    "You are controlling a browser that has been navigated to an unsubscribe page.\n\n"
                    f"The user's email address is: {user_email}\n\n"
                    "Your goal: Complete the unsubscribe process on this page. This may involve:\n"
                    "- Clicking an 'Unsubscribe' or 'Confirm' button\n"
                    "- Checking/unchecking checkboxes for mailing list preferences\n"
                    "- Filling in the user's email address in a form field\n"
                    "- Clicking 'Submit' or 'Update Preferences' buttons\n\n"
                    "IMPORTANT RULES:\n"
                    "- Take a screenshot first to see the current page state\n"
                    "- If you see a confirmation that you've been unsubscribed, call the "
                    "`report_unsubscribe_status` tool with status=\"success\" — that ends the run.\n"
                    "- If there are checkboxes to unsubscribe from lists, uncheck ALL of them "
                    "(or check the 'unsubscribe from all' option), then submit\n"
                    "- If asked for an email, type the user's email address\n"
                    "- If you see a CAPTCHA or login wall, call `report_unsubscribe_status` with "
                    "status=\"needs_human\" — you cannot proceed.\n"
                    "- If the page errors out or the unsubscribe cannot be completed for any other "
                    "reason, call `report_unsubscribe_status` with status=\"failure\".\n"
                    "- Be precise with your clicks. Click directly on buttons and checkboxes.\n"
                    "- After taking an action, take a screenshot to verify the result.\n"
                    "- ALWAYS finish by calling `report_unsubscribe_status` exactly once."
                )

                messages = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Please unsubscribe me from this mailing list. Here is the current page:",
                            },
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": full_b64,
                                },
                            },
                        ],
                    }
                ]

                for iteration in range(MAX_CU_ITERATIONS):
                    # Call Claude with Computer Use
                    try:
                        response = await asyncio.to_thread(
                            client.beta.messages.create,
                            model=self.model,
                            max_tokens=1024,
                            system=system_prompt,
                            tools=tools,
                            messages=messages,
                            betas=[self.cu_beta],
                        )
                    except Exception as e:
                        logger.error(f"Computer Use API call failed: {e}")
                        yield UnsubscribeEvent(
                            step="error",
                            message=f"AI call failed: {e}",
                            status="failed",
                            error=str(e),
                        )
                        return

                    # Process the response
                    assistant_content = response.content
                    messages.append({"role": "assistant", "content": assistant_content})

                    # Check if Claude is done (end_turn with no tool use)
                    has_tool_use = any(
                        getattr(block, "type", None) == "tool_use"
                        for block in assistant_content
                    )

                    # Extract text reasoning from the response
                    reasoning_parts = []
                    for block in assistant_content:
                        if getattr(block, "type", None) == "text" and block.text.strip():
                            reasoning_parts.append(block.text.strip())
                    reasoning = " ".join(reasoning_parts) if reasoning_parts else ""

                    # Did the model report a final status via the structured tool?
                    # If so, that is authoritative — short-circuit the loop and use
                    # its language-independent answer instead of keyword matching.
                    status_block = next(
                        (
                            b for b in assistant_content
                            if getattr(b, "type", None) == "tool_use"
                            and b.name == UNSUBSCRIBE_STATUS_TOOL["name"]
                        ),
                        None,
                    )
                    if status_block is not None:
                        status_input = status_block.input or {}
                        reported = status_input.get("status", "failure")
                        reason = status_input.get("reason", "") or reasoning
                        success = reported == "success"
                        _, _, final_thumb = await self._take_screenshot(page)
                        yield UnsubscribeEvent(
                            step="completed",
                            message=(
                                "Successfully unsubscribed!" if success
                                else f"Stopped ({reported}): {reason[:200]}"
                            ),
                            screenshot_b64=final_thumb,
                            llm_reasoning=reasoning or reason,
                            status="success" if success else "failed",
                            error=None if success else reason[:200],
                        )
                        return

                    if not has_tool_use:
                        # Model returned plain text without calling the status tool.
                        # Fall back to the legacy English-keyword heuristic so we
                        # do not lose the run, but log a warning — the structured
                        # tool is the preferred path.
                        logger.warning(
                            "Unsubscribe model ended turn without report_unsubscribe_status; "
                            "falling back to keyword detection"
                        )
                        reasoning_lower = reasoning.lower()
                        success = any(
                            kw in reasoning_lower
                            for kw in [
                                "unsubscribed", "successfully", "completed",
                                "confirmed", "you have been", "opted out",
                                "removed", "preferences updated", "done",
                            ]
                        )

                        _, _, final_thumb = await self._take_screenshot(page)
                        yield UnsubscribeEvent(
                            step="completed",
                            message="Successfully unsubscribed!" if success else f"Process ended: {reasoning[:200]}",
                            screenshot_b64=final_thumb,
                            llm_reasoning=reasoning,
                            status="success" if success else "failed",
                            error=None if success else reasoning[:200],
                        )
                        return

                    # Process tool use blocks
                    tool_results = []
                    for block in assistant_content:
                        if getattr(block, "type", None) != "tool_use":
                            continue
                        # The status tool was already handled above.
                        if block.name == UNSUBSCRIBE_STATUS_TOOL["name"]:
                            continue

                        tool_input = block.input
                        action_name = tool_input.get("action", "unknown")

                        if action_name == "screenshot":
                            # Claude wants a fresh screenshot
                            _, fresh_b64, fresh_thumb = await self._take_screenshot(page)
                            yield UnsubscribeEvent(
                                step=f"screenshot_{iteration + 1}",
                                message="Taking screenshot...",
                                screenshot_b64=fresh_thumb,
                                llm_reasoning=reasoning,
                            )
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": [
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": "image/png",
                                            "data": fresh_b64,
                                        },
                                    }
                                ],
                            })
                        elif action_name == "cursor_position":
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": [{"type": "text", "text": f"Cursor at (640, 450)"}],
                            })
                        else:
                            # Execute the action
                            action_desc = await self._execute_computer_action(page, tool_input)
                            logger.info(f"Computer Use action: {action_desc}")

                            # Brief pause for page to react
                            await page.wait_for_timeout(1500)
                            try:
                                await page.wait_for_load_state("domcontentloaded", timeout=3000)
                            except Exception:
                                pass

                            # Take screenshot after action
                            _, post_b64, post_thumb = await self._take_screenshot(page)

                            yield UnsubscribeEvent(
                                step=f"acting_{iteration + 1}",
                                message=f"{action_desc}",
                                screenshot_b64=post_thumb,
                                llm_reasoning=reasoning,
                            )

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": [
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": "image/png",
                                            "data": post_b64,
                                        },
                                    }
                                ],
                            })

                    messages.append({"role": "user", "content": tool_results})

                # Exhausted iterations
                _, _, final_thumb = await self._take_screenshot(page)
                yield UnsubscribeEvent(
                    step="max_iterations",
                    message=f"Reached maximum of {MAX_CU_ITERATIONS} steps. May need manual review.",
                    screenshot_b64=final_thumb,
                    status="failed",
                    error="Max iterations reached",
                )

            except Exception as e:
                logger.error(f"Playwright unsubscribe error for {url}: {e}")
                err_b64 = None
                try:
                    _, _, err_b64 = await self._take_screenshot(page)
                except Exception:
                    pass

                yield UnsubscribeEvent(
                    step="error",
                    message=f"Browser error: {str(e)}",
                    screenshot_b64=err_b64,
                    status="failed",
                    error=str(e),
                )
            finally:
                await browser.close()

    async def unsubscribe_via_email(
        self,
        gmail_service,
        unsub_info: dict,
    ) -> UnsubscribeEvent:
        """Send an unsubscribe email via Gmail API."""
        unsub_email_to = unsub_info.get("email")
        subject = unsub_info.get("mailto_subject", "unsubscribe")
        body_text = unsub_info.get("mailto_body", "")
        if not body_text:
            body_text = "Please unsubscribe me from this mailing list. Thank you."

        if not unsub_email_to:
            return UnsubscribeEvent(
                step="error",
                message="No unsubscribe email address found",
                status="failed",
                error="No mailto address in unsubscribe info",
            )

        try:
            await gmail_service.send_email(
                to=[unsub_email_to],
                subject=subject,
                body_text=body_text,
            )
            return UnsubscribeEvent(
                step="completed",
                message=f"Unsubscribe email sent to {unsub_email_to}",
                status="success",
            )
        except Exception as e:
            logger.error(f"Failed to send unsubscribe email to {unsub_email_to}: {e}")
            return UnsubscribeEvent(
                step="error",
                message=f"Failed to send unsubscribe email: {e}",
                status="failed",
                error=str(e),
            )

    async def mark_as_spam(
        self,
        gmail_service,
        gmail_message_id: str,
    ) -> bool:
        """Mark an email as spam in Gmail."""
        try:
            await gmail_service.modify_labels(
                gmail_message_id,
                add_labels=["SPAM"],
                remove_labels=["INBOX"],
            )
            return True
        except Exception as e:
            logger.error(f"Failed to mark message {gmail_message_id} as spam: {e}")
            return False
