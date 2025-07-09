import asyncio
import google.generativeai as genai
from mcp_use import MCPAgent, MCPClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.tools import Tool
from typing import List, Optional


class GeminiLLMWrapper(BaseChatModel):
    def __init__(self, api_key: str, model_name: str = "models/gemini-2.5-pro", temperature: float = 0.3):
        super().__init__()
        genai.configure(api_key=api_key) 
        self._model = genai.GenerativeModel(model_name)
        self._model_name = model_name
        self._temperature = temperature

    def _llm_type(self) -> str:
        return "gemini"

    def bind_tools(self, tools: Optional[List[Tool]] = None):
        # Gemini doesn't support LangChain's tool binding
        return self

    async def ainvoke(self, input, **kwargs) -> BaseMessage:
        try:
            messages = input.to_messages()
        except AttributeError:
            messages = input

        prompt = "\n".join([m.content for m in messages if hasattr(m, "content")])
        response = await self._model.generate_content_async(prompt)

        try:
            text = response.text
        except AttributeError:
            try:
                text = response.candidates[0].content.parts[0].text
            except Exception:
                text = "[ERROR] Gemini response format unexpected."

        return AIMessage(content=text)

    async def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None) -> ChatResult:
        prompt = "\n".join([m.content for m in messages if hasattr(m, "content")])
        response = await self._model.generate_content_async(prompt)

        try:
            text = response.text
        except AttributeError:
            try:
                text = response.candidates[0].content.parts[0].text
            except Exception:
                text = "[ERROR] Gemini response format unexpected."

        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


async def main():
    client = MCPClient(config={
        "mcpServers": {
            "sonarqubemcp": {
                "command": "python",
                "args": ["sonar_git_mcp.py"],
                "env": {
                    "SONARQUBE_URL": "",
                    "SONARQUBE_TOKEN": "",
                    "PROJECT_KEY": "",
                    "GITHUB_TOKEN": "",
                    "GITHUB_REPO": "",
                    "GITHUB_USER": ""
                }
            }
        }
    })

    try:
        llm = GeminiLLMWrapper(api_key="")
    except Exception as e:
        print(" Failed to initialize Gemini LLM:", e)
        return

    agent = MCPAgent(llm=llm, client=client, max_steps=30)

    try:
        result = await agent.run("Check if there are unresolved issues in SonarQube")
        print(" Result:", result)
    except Exception as e:
        print(" Agent execution failed:", e)


if __name__ == "__main__":
    asyncio.run(main())
