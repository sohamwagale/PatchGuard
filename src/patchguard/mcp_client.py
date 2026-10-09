import asyncio

from mcp import ClientSession , StdioServerParameters
from mcp.client.stdio import stdio_client

server_params = StdioServerParameters(
  command="python",
  args=["src/patchguard/mcp_server.py"]
)

async def main():
  async with stdio_client(server_params) as (read,write):
    async with ClientSession(read,write) as session:
      await session.initialize()

      # print("here")
      # result = await session.list_tools()
      # for tool in result.tools:
      #   print(tool.name)

      # result = await session.call_tool(
      #   "read_file",
      #   {"path":"sample.txt"}
      # )

      result = await session.call_tool(
        "search_code",
        {"query": "this-thing-does-not-exist"},
      )

      # print(result.content)
      print(result.structured_content["result"]) #The above one didnt work properly

if __name__=="__main__":
  asyncio.run(main())