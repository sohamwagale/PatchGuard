import os

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("PatchGuard")

@mcp.tool()
def read_file(path:str)->str:
  """Read a file from the repository."""
  with open(path,"r",encoding="utf-8") as file:
    return file.read()



@mcp.tool()
def search_code(query:str) -> str:
  """Search for a text string in the repository."""
  matches = []

  for root,_,files in os.walk("."):
    for filename in files:
      path = os.path.join(root,filename)

      try:
        with open(path,"r",encoding="utf-8") as file:
          for line_number,line in enumerate(file,start=1):
            if query in line:
              matches.append(
                f"{path}:{line_number}: {line.rstrip()}"
              )
      except (UnicodeDecodeError,PermissionError):
        continue

  return "\n".join(matches)



if __name__ == "__main__":
  mcp.run(transport='stdio')