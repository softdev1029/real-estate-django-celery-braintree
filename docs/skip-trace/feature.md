Skip Trace
==========

In Lead Sherpa, the skip trace subsystem serves the purpose of doing a reverse
lookup based on property address to yield some metadata about the most recent
owner(s), most specifically their last known contact information.

Workflow
--------

From the frontend, a user is redirected to FlatFile where they are asked to map
the fields of the upload candidates (property addresses) to our internal field
names.  Once that is complete, the yielded file is handed back to the frontend
and it uploads it to the "map-fields" endpoint, which takes the normalized data
as input and stores the source file and field mappings as an UploadSkipTrace
record.  At the time the file is uploaded, the user is provided with a few
options.  The first is whether or not they want to preferentially fall through
to the database, or refresh all records in the uploaded file (the latter will
potentially cost them more money).  The second is a list of tags they want
applied to each property yielded by the skip trace.
