# Litgators

## Uploading Litigators

The `UploadLitigatorList` has a `.post_save()` signal (litigation.signals.litigator_uploaded) that will fire the `upload_litigator_list_task` task (litigation.tasks.upload_litigator_list_task). The uploaded CSV only checks the first column and will only handle the `file` property from the instance.

> All litigators created via the task are set under the Cedar Crest Properties (id: 1) company.

The admin section for this model has been updated with a custom add form (litigation.forms.LitigatorUploadCustomAddForm) only allowing the file to be uploaded and setting `created_by` to the current admin user.
