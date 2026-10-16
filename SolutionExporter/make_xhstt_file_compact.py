import sys
sys.path.append('../XHSTTImporter')
sys.path.append('XHSTTImporter')
from Instance import Instance
sys.path.append('../XHSTTImporter/Constants')
sys.path.append('XHSTTImporter/Constants')
import XHSTTFileConstants
import XHSTTConstraintConstants


def combine_XHSTT_constraints(instance: Instance):
    for constraintType in instance.Constraints.keys():
        dictOfEquivalentConstraints = dict()
        for constraint in instance.Constraints[constraintType]:
            fieldValues = list()
            # Balance class size constraints cant be combined as that would change semantics
            if constraintType == XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT:
                fieldValues.append((XHSTTConstraintConstants.ID, tuple([constraint[XHSTTConstraintConstants.ID]])))
            for field in constraint.keys():
                if field == XHSTTConstraintConstants.NAME or field == XHSTTConstraintConstants.ID or field == XHSTTConstraintConstants.APPLIES_TO or field == XHSTTConstraintConstants.DEVIATION_MAP or field == XHSTTConstraintConstants.IS_FULFILLED or field == XHSTTConstraintConstants.DEVIATION_VECTOR or field == XHSTTConstraintConstants.OBJECTIVE_VALUE or field == XHSTTConstraintConstants.DEVIATION_EVENTS:
                    continue
                if isinstance(constraint[field], list):
                    for entry in constraint[field]:
                        if isinstance(entry, dict):
                            fieldValues.append((field, tuple(entry.items())))
                        else:
                            fieldValues.append((field, tuple([entry])))
                elif isinstance(constraint[field], dict):
                    fieldValues.append((field, tuple(constraint[field].items())))
                else:
                    fieldValues.append((field, tuple([constraint[field]])))
            fieldValues = tuple(fieldValues)
            dictOfEquivalentConstraints.setdefault(fieldValues, list())
            dictOfEquivalentConstraints[fieldValues].append(constraint)
        counter = 0
        for constraint in dictOfEquivalentConstraints.keys():
            baseConstraint = dictOfEquivalentConstraints[constraint][0]
            for application in baseConstraint[XHSTTConstraintConstants.APPLIES_TO]:
                if len(dictOfEquivalentConstraints[constraint]) > 1:
                    for otherConstraint in dictOfEquivalentConstraints[constraint][1:]:
                        baseConstraint[XHSTTConstraintConstants.APPLIES_TO][application] += otherConstraint[XHSTTConstraintConstants.APPLIES_TO][application]
            baseConstraint[XHSTTConstraintConstants.NAME] = constraintType + str(counter)
            baseConstraint[XHSTTConstraintConstants.ID] = constraintType + str(counter)
            counter += 1
            if len(dictOfEquivalentConstraints[constraint]) > 1:
                for otherConstraint in dictOfEquivalentConstraints[constraint][1:]:
                    instance.Constraints[constraintType].remove(otherConstraint)
            if constraintType == XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT and len(baseConstraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]) == 1:
                instance.Constraints[constraintType].remove(baseConstraint)