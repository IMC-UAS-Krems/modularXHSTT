import sys
sys.path.append('XHSTTImporter')
sys.path.append('../XHSTTImporter')
from Instance import XHSTTInstance
from Constants import XHSTTFileConstants, XHSTTConstraintConstants

def create_empty_XHSTT_instance(filename: str) -> XHSTTInstance:
    instance = XHSTTInstance({
        XHSTTFileConstants.METADATA: {
            XHSTTFileConstants.FILE_ID: filename[:-4],
            XHSTTFileConstants.FILE_NAME: filename
        },
        XHSTTFileConstants.RESOURCES: {
            XHSTTFileConstants.RESOURCE_GROUPS_BY_TYPE: {},
            XHSTTFileConstants.INDIVIDUAL_RESOURCES: {}
        },
        XHSTTFileConstants.TIMES: {
            XHSTTFileConstants.DAYS: {},
            XHSTTFileConstants.INDIVIDUAL_TIMES: {},
            XHSTTFileConstants.TIME_GROUPS: {}
        },
        XHSTTFileConstants.EVENTS: {
            XHSTTFileConstants.EVENT_GROUPS: {},
            XHSTTFileConstants.INDIVIDUAL_EVENTS: {}
        },
        XHSTTFileConstants.CONSTRAINTS: {
            XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT: [],
            XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT: [],
            XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT: [],
            XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT: [],
            XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT: [],
            XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT: [],
            XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT: [],
            XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT: [],
            XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT: [],
            XHSTTConstraintConstants.ORDER_EVENTS_CONSTRAINT: [],
            XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT: [],
            XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT: [],
            XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT: [],
            XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT: [],
            XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT: [],
            XHSTTConstraintConstants.LIMIT_WORKLOAD_CONSTRAINT: [],
            XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT: [],
            XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT: [],
        }
    })
    return instance