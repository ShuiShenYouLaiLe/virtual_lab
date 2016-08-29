from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from ..models import Course, Registered_Course, Virtual_Machine, User_VM_Config
from ..forms import Course_Registration_Form
from ..utils import audit, XenClient
import logging
from subprocess import Popen, PIPE

logger = logging.getLogger(__name__)


# Create your views here.


@login_required(login_url='/vital/login/')
def registered_courses(request):
    logger.debug("In registered courses")
    #  reg_courses = Registered_Courses.objects.filter(user_id=request.user.id, course__status='ACTIVE')
    reg_courses = Registered_Course.objects.filter(user_id=request.user.id)
    message = ''
    if len(reg_courses) == 0:
        message = 'You have no registered courses'
    return render(request, 'vital/registered_courses.html', {'reg_courses': reg_courses, 'message':message})


@login_required(login_url='/vital/login/')
def course_vms(request, course_id):
    logger.debug("in course vms")
    virtual_machines = Virtual_Machine.objects.filter(course_id=course_id)
    for vm in virtual_machines:
        user_vm_configs = vm.user_vm_config_set.filter(user_id=request.user.id)
        if user_vm_configs is not None and not len(user_vm_configs) == 0:
            vm.state = 'R'
            user_vm_configs = vm.user_vm_config_set.filter(user_id=request.user.id)
            for config in user_vm_configs:
                if config.vm.id == vm.id:
                    vm.terminal_port = config.terminal_port
                    break
        else:
            vm.state = 'S'
    return render(request, 'vital/course_vms.html', {'virtual_machines': virtual_machines, 'course_id':course_id})


@login_required(login_url='/vital/login/')
def unregister_from_course(request, course_id):
    logger.debug("in course unregister")
    user = request.user
    reg_courses = Registered_Course.objects.filter(course_id=course_id, user_id=user.id)
    course_to_remove = reg_courses[0]
    XenClient().unregister_student_vms(request.user, course_to_remove.course)
    audit(request, course_to_remove, 'User '+str(user.id)+' unregistered from course -'+str(course_id))
    course_to_remove.delete()
    return redirect('/vital/courses/registered/')


@login_required(login_url='/vital/login/')
def start_vm(request, course_id, vm_id):
    try:
        vm = Virtual_Machine.objects.get(pk=vm_id)
        config = User_VM_Config()
        config.vm = vm
        config.user_id = request.user.id
        # start vm with xen api which returns handle to the vm
        started_vm = XenClient().start_vm(request.user, course_id, vm_id)
        config.vnc_port = started_vm['vnc_port']
        # run novnc launch script
        # TODO replace vlab-dev-xen1 with configured values <based on LB & already existing vms>
        cmd = 'nohup sh /var/www/clone.com/interim/noVNC/utils/launch.sh --vnc vlab-dev-xen1:'+started_vm['vnc_port']+\
              ' &'
        p = Popen(cmd, shell=True, stdout=PIPE, stderr=PIPE)
        out, err = p.communicate()
        if not p.returncode == 0:
            raise Exception('ERROR : cannot start the vm. \n Reason : %s' % err.rstrip())
        config.no_vnc_pid = p.pid
        output = out.rstrip()
        config.vnc_port = output[output.index('port=')+5:output.index('Press')].strip()
        config.save()
    except Virtual_Machine.DoesNotExist as e:
        logger.error(str(e))


def dummy_console(request):
    return render(request, 'vital/dummy.html')


@login_required(login_url='/vital/login/')
def register_for_course(request):
    logger.debug("in register for course")
    error_message = ''
    if request.method == 'POST':
        form = Course_Registration_Form(request.POST)
        if form.is_valid():
            logger.debug(form.cleaned_data['course_registration_code']+"<>"+str(request.user.id)+"<>"+
                         str(request.user.is_faculty))
            try:
                course = Course.objects.get(registration_code=form.cleaned_data['course_registration_code'])
                user = request.user
                if len(Registered_Course.objects.filter(course_id=course.id, user_id=user.id)) > 0:
                        error_message = 'You have already registered for this course'
                else:
                    if course.capacity > len(Registered_Course.objects.filter(course_id=course.id)) \
                            and course.status == 'ACTIVE':
                        XenClient().register_student_vms(request.user, course)
                        registered_course = Registered_Course(course_id=course.id, user_id=user.id)
                        registered_course.save()
                        audit(request, registered_course, 'User '+str(user.id)+' registered for new course -'+str(course.id))
                        return redirect('/vital/courses/registered/')
                    else:
                        error_message = 'The course is either inactive or has reached its maximum student capacity.'
            except Course.DoesNotExist:
                error_message = 'Invalid registration code. Check again.'
    else:
        form = Course_Registration_Form()
    return render(request, 'vital/course_register.html', {'form': form, 'error_message': error_message})