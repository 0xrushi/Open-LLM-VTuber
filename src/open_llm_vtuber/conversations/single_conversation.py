from typing import Union, List, Dict, Any, Optional
import asyncio
import json
import time
import uuid
from loguru import logger
import numpy as np

from .conversation_utils import (
    create_batch_input,
    process_agent_output,
    send_conversation_start_signals,
    process_user_input,
    finalize_conversation_turn,
    cleanup_conversation,
    EMOJI_LIST,
)
from .types import WebSocketSend
from .tts_manager import TTSTaskManager
from ..chat_history_manager import store_message
from ..service_context import ServiceContext
from ..scene_action_skill import resolve_scene_action_from_text

# Import necessary types from agent outputs
from ..agent.output_types import SentenceOutput, AudioOutput
from ..agent.output_types import Actions, DisplayText
from ..skills.weather_timer.skill import (
    format_timer_complete_response,
    format_timer_set_response,
    format_weather_response,
    get_weather,
    resolve_weather_timer_intent,
)


async def _speak_utility_text(
    text: str,
    context: ServiceContext,
    websocket_send: WebSocketSend,
    tts_manager: TTSTaskManager,
) -> str:
    return await process_agent_output(
        output=SentenceOutput(
            display_text=DisplayText(text=text),
            tts_text=text,
            actions=Actions(expressions=["neutral"]),
        ),
        character_config=context.character_config,
        live2d_model=context.live2d_model,
        tts_engine=context.tts_engine,
        websocket_send=websocket_send,
        tts_manager=tts_manager,
        translate_engine=context.translate_engine,
    )


async def _complete_timer_later(context: ServiceContext, seconds: int) -> None:
    await asyncio.sleep(seconds)
    await context._speak_background_tool_result(format_timer_complete_response(seconds))


async def process_single_conversation(
    context: ServiceContext,
    websocket_send: WebSocketSend,
    client_uid: str,
    user_input: Union[str, np.ndarray],
    images: Optional[List[Dict[str, Any]]] = None,
    session_emoji: str = np.random.choice(EMOJI_LIST),
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Process a single-user conversation turn

    Args:
        context: Service context containing all configurations and engines
        websocket_send: WebSocket send function
        client_uid: Client unique identifier
        user_input: Text or audio input from user
        images: Optional list of image data
        session_emoji: Emoji identifier for the conversation
        metadata: Optional metadata for special processing flags

    Returns:
        str: Complete response text
    """
    turn_id = uuid.uuid4().hex[:8]
    chain_t0 = time.perf_counter()
    # Create TTSTaskManager for this conversation
    tts_manager = TTSTaskManager(turn_id=turn_id)
    full_response = ""  # Initialize full_response here

    if hasattr(context, "mark_turn_start"):
        context.mark_turn_start()

    try:
        # Send initial signals
        await send_conversation_start_signals(websocket_send, turn_id=turn_id)
        logger.info(f"New Conversation Chain {session_emoji} started! turn={turn_id}")

        # Process user input
        input_text = await process_user_input(
            user_input, context.asr_engine, websocket_send
        )

        scene_action = resolve_scene_action_from_text(input_text)
        if scene_action:
            if context.history_uid:
                store_message(
                    conf_uid=context.character_config.conf_uid,
                    history_uid=context.history_uid,
                    role="human",
                    content=input_text,
                    name=context.character_config.human_name,
                )
            await websocket_send(
                json.dumps(
                    {
                        "type": "scene-action",
                        "action": scene_action.action,
                        "objectId": scene_action.object_id,
                        "sourceText": input_text,
                    }
                )
            )
            logger.info(
                f"Handled scene action without LLM: action={scene_action.action} object={scene_action.object_id}"
            )
            await finalize_conversation_turn(
                tts_manager=tts_manager,
                websocket_send=websocket_send,
                client_uid=client_uid,
            )
            return ""

        utility_action = resolve_weather_timer_intent(input_text)
        if utility_action:
            if context.history_uid:
                store_message(
                    conf_uid=context.character_config.conf_uid,
                    history_uid=context.history_uid,
                    role="human",
                    content=input_text,
                    name=context.character_config.human_name,
                )

            if utility_action.kind == "weather":
                try:
                    weather = await asyncio.to_thread(
                        get_weather,
                        utility_action.location or "shadyside",
                    )
                    full_response = await _speak_utility_text(
                        format_weather_response(weather),
                        context,
                        websocket_send,
                        tts_manager,
                    )
                except Exception as exc:
                    logger.error(f"Weather skill failed: {exc}")
                    full_response = await _speak_utility_text(
                        f"[sadness] [sigh] I could not get the weather right now: {exc}",
                        context,
                        websocket_send,
                        tts_manager,
                    )
            elif utility_action.kind == "timer" and utility_action.seconds:
                seconds = utility_action.seconds
                asyncio.create_task(_complete_timer_later(context, seconds))
                full_response = await _speak_utility_text(
                    format_timer_set_response(seconds),
                    context,
                    websocket_send,
                    tts_manager,
                )

            if tts_manager.task_list:
                await asyncio.gather(*tts_manager.task_list)
                await websocket_send(json.dumps({"type": "backend-synth-complete"}))

            await finalize_conversation_turn(
                tts_manager=tts_manager,
                websocket_send=websocket_send,
                client_uid=client_uid,
            )

            if context.history_uid and full_response:
                store_message(
                    conf_uid=context.character_config.conf_uid,
                    history_uid=context.history_uid,
                    role="ai",
                    content=full_response,
                    name=context.character_config.character_name,
                    avatar=context.character_config.avatar,
                )
            return full_response

        # Create batch input
        batch_input = create_batch_input(
            input_text=input_text,
            images=images,
            from_name=context.character_config.human_name,
            metadata=metadata,
        )

        # Store user message (check if we should skip storing to history)
        skip_history = metadata and metadata.get("skip_history", False)
        if context.history_uid and not skip_history:
            store_message(
                conf_uid=context.character_config.conf_uid,
                history_uid=context.history_uid,
                role="human",
                content=input_text,
                name=context.character_config.human_name,
            )

        if skip_history:
            logger.debug("Skipping storing user input to history (proactive speak)")

        logger.info(f"User input: {input_text}")
        if images:
            logger.info(f"With {len(images)} images")

        try:
            if hasattr(context.agent_engine, "set_runtime_tooling"):
                context.agent_engine.set_runtime_tooling(
                    tool_manager=context.tool_manager,
                    tool_executor=context.tool_executor,
                    mcp_prompt_string=context.mcp_prompt,
                )

            # agent.chat yields Union[SentenceOutput, Dict[str, Any]]
            llm_t0 = time.perf_counter()
            first_agent_item_ms: float | None = None
            agent_output_stream = context.agent_engine.chat(batch_input)

            async for output_item in agent_output_stream:
                if first_agent_item_ms is None:
                    first_agent_item_ms = (time.perf_counter() - llm_t0) * 1000
                    logger.info(
                        f"[PERF][AGENT] turn={turn_id} first_item_ms={first_agent_item_ms:.1f}"
                    )

                if (
                    isinstance(output_item, dict)
                    and output_item.get("type") == "tool_call_status"
                ):
                    # Handle tool status event: send WebSocket message
                    output_item["name"] = context.character_config.character_name
                    logger.debug(f"Sending tool status update: {output_item}")

                    await websocket_send(json.dumps(output_item))

                elif isinstance(output_item, (SentenceOutput, AudioOutput)):
                    # Handle SentenceOutput or AudioOutput
                    response_part = await process_agent_output(
                        output=output_item,
                        character_config=context.character_config,
                        live2d_model=context.live2d_model,
                        tts_engine=context.tts_engine,
                        websocket_send=websocket_send,  # Pass websocket_send for audio/tts messages
                        tts_manager=tts_manager,
                        translate_engine=context.translate_engine,
                    )
                    # Ensure response_part is treated as a string before concatenation
                    response_part_str = (
                        str(response_part) if response_part is not None else ""
                    )
                    full_response += response_part_str  # Accumulate text response
                else:
                    logger.warning(
                        f"Received unexpected item type from agent chat stream: {type(output_item)}"
                    )
                    logger.debug(f"Unexpected item content: {output_item}")

        except Exception as e:
            logger.exception(
                f"Error processing agent response stream: {e}"
            )  # Log with stack trace
            await websocket_send(
                json.dumps(
                    {
                        "type": "error",
                        "message": f"Error processing agent response: {str(e)}",
                    }
                )
            )
            # full_response will contain partial response before error
        # --- End processing agent response ---

        # Wait for any pending TTS tasks
        if tts_manager.task_list:
            await asyncio.gather(*tts_manager.task_list)
            await websocket_send(json.dumps({"type": "backend-synth-complete"}))

        await finalize_conversation_turn(
            tts_manager=tts_manager,
            websocket_send=websocket_send,
            client_uid=client_uid,
        )

        if context.history_uid and full_response:  # Check full_response before storing
            store_message(
                conf_uid=context.character_config.conf_uid,
                history_uid=context.history_uid,
                role="ai",
                content=full_response,
                name=context.character_config.character_name,
                avatar=context.character_config.avatar,
            )
            logger.info(f"AI response: {full_response}")

        logger.info(
            f"[PERF][TURN] turn={turn_id} total_ms={(time.perf_counter()-chain_t0)*1000:.1f}"
        )
        return full_response  # Return accumulated full_response

    except asyncio.CancelledError:
        logger.info(f"🤡👍 Conversation {session_emoji} cancelled because interrupted.")
        raise
    except Exception as e:
        logger.error(f"Error in conversation chain: {e}")
        await websocket_send(
            json.dumps({"type": "error", "message": f"Conversation error: {str(e)}"})
        )
        raise
    finally:
        if hasattr(context, "mark_turn_end"):
            context.mark_turn_end()
        cleanup_conversation(tts_manager, session_emoji)
