from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Literal

class ToolAuth(BaseModel):
    type: Literal["none", "api_key", "bearer"] = "none"
    key: Optional[str] = None  # environment variable name, e.g., ${FDA_API_KEY}
    # For more complex auth, we can extend later

class ToolRateLimit(BaseModel):
    calls_per_minute: Optional[int] = None
    calls_per_day: Optional[int] = None

class ToolConfig(BaseModel):
    name: str
    description: Optional[str] = None
    type: Literal["api", "function", "vector_db", "web_search"] = "function"
    module: str  # Python module path, e.g., "tools.implementations.openfda"
    class_name: str  # Class name in that module
    config: Dict[str, Any] = Field(default_factory=dict)  # Tool-specific parameters
    auth: ToolAuth = Field(default_factory=ToolAuth)
    rate_limit: ToolRateLimit = Field(default_factory=ToolRateLimit)
    enabled: bool = True
