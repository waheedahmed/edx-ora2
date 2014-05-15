"""
Student training step in the OpenAssessment XBlock.
"""
import logging
from django.utils.translation import ugettext as _
from webob import Response
from xblock.core import XBlock
from openassessment.assessment.api import student_training


logger = logging.getLogger(__name__)


class StudentTrainingMixin(object):
    """
    Student training is a step that allows students to practice
    assessing example essays provided by the course author.

    1) A student is shown an example essay.
    2) The student scores the example essay.
        a) If the student's scores match the instructor's scores,
            the student is shown the next example.  If there are no
            more examples, the step is marked complete.
        b) If the student's scores do NOT match the instructor's scores,
            the student is prompted to retry.

    """

    @XBlock.handler
    def render_student_training(self, data, suffix=''):   # pylint:disable=W0613
        """
        Render the student training step.

        Args:
            data: Not used.

        Kwargs:
            suffix: Not used.

        Returns:
            unicode: HTML content of the grade step

        """
        if "training" not in self.assessment_steps:
            return Response(u"")

        try:
            path, context = self.training_path_and_context()
        except: # pylint:disable=W0702
            msg = u"Could not render student training step for submission {}".format(self.submission_uuid)
            logger.exception(msg)
            return self.render_error(_(u"An unexpected error occurred."))
        else:
            return self.render_assessment(path, context)

    def training_path_and_context(self):
        """
        Return the template path and context used to render the student training step.

        Returns:
            tuple of `(path, context)` where `path` is the path to the template and
                `context` is a dict.

        """
        # Retrieve the status of the workflow.
        # If no submissions have been created yet, the status will be None.
        workflow_status = self.get_workflow_info().get('status')
        problem_closed, reason, start_date, due_date = self.is_closed(step="student-training")

        context = {}
        template = 'openassessmentblock/student_training/student_training_unavailable.html'

        # If the student has completed the training step, then show that the step is complete.
        # We put this condition first so that if a student has completed the step, it *always*
        # shows as complete.
        # We're assuming here that the training step always precedes the other assessment steps
        # (peer/self) -- we may need to make this more flexible later.
        if workflow_status in ['peer', 'self', 'waiting', 'done']:
            template = 'openassessmentblock/student_training/student_training_complete.html'

        # If the problem is closed, then do not allow students to access the training step
        elif problem_closed and reason == 'start':
            context['training_start'] = start_date
            template = 'openassessmentblock/student_training/student_training_unavailable.html'
        elif problem_closed and reason == 'due':
            context['training_due'] = due_date
            template = 'openassessmentblock/student_training/student_training_closed.html'

        # If we're on the training step, show the student an example
        # We do this last so we can avoid querying the student training API if possible.
        else:
            # Report progress in the student training workflow (completed X out of Y)
            status = student_training.get_workflow_status(self.submission_uuid)
            context['training_num_completed'] = status['num_completed']
            context['training_num_available'] = status['num_total']

            # Retrieve the example essay for the student to submit
            # This will contain the essay text, the rubric, and the options the instructor selected.
            example = student_training.get_training_example(self.submission_uuid)
            context['training_essay'] = example['answer']
            context['training_rubric'] = example['rubric']
            template = 'openassessmentblock/student_training/student_training.html'

        return template, context

    @XBlock.json_handler
    def training_assess(self, data, suffix=''): # pylint:disable=W0613
        """
        Compare the scores given by the student with those given by the course author.
        If they match, update the training workflow.  The client can then reload this
        step to view the next essay or the completed step.

        Currently, we return a boolean indicating whether the student assessed correctly
        or not.  However, the student training API provides the exact criteria that the student
        scored incorrectly, as well as the "correct" options for those criteria.
        In the future, we may expose this in the UI to provide more detailed feedback.

        Args:
            data (dict): Must have the following keys:
                options_selected (dict): Dictionary mapping criterion names to option values.

        Returns:
            Dict with keys:
                * "success" (bool) indicating success or error
                * "msg" (unicode) containing additional information if an error occurs.
                * "correct" (bool) indicating whether the student scored the assessment correctly.

        """
        if 'options_selected' not in data:
            return {'success': False, 'msg': _(u"Missing options_selected key in request")}
        if not isinstance(data['options_selected'], dict):
            return {'success': False, 'msg': _(u"options_selected must be a dictionary")}

        # Check the student's scores against the course author's scores.
        # This implicitly updates the student training workflow (which example essay is shown)
        # as well as the assessment workflow (training/peer/self steps).
        try:
            corrections = student_training.assess_training_example(
                self.submission_uuid, data['options_selected']
            )
        except (student_training.StudentTrainingRequestError, student_training.StudentTrainingInternalError) as ex:
            return {
                'success': False,
                'msg': _(u"Your scores could not be checked: {error}.").format(error=ex.message)
            }
        except:
            return {
                'success': False,
                'msg': _(u"An unexpected error occurred.")
            }
        else:
            return {
                'success': True,
                'msg': u'',
                'correct': len(corrections) == 0,
            }
