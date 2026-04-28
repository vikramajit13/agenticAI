from enum import Enum

class Action(Enum):
    REGENERATEAC = "Regenerate_Acceptance_Criteria"
    SPLITSTORY = "Split_User_Story"
    TECHNICALSTORY = "Technical_Story"
    NOACTION = ""