from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

source = Path(__file__).resolve().parents[3] / "核心源码" / "agent.py"
spec = spec_from_file_location("distributed_agent_core", source)
module = module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
Agent = module.Agent
Candidate = module.Candidate
Response = module.Response
Proposal = module.Proposal
Message = module.Message
Task = module.Task
Transport = module.Transport
Clock = module.Clock
run_agent = module.run_agent
