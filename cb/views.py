from django.shortcuts import render
from drf_chunked_upload.exceptions import ChunkedUploadError
from drf_chunked_upload.views import ChunkedUploadView
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated


# Create your views here.
class DataChunkedUploadView(ChunkedUploadView):
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser,)

    def _put_chunk(self, request, pk=None, whole=False, *args, **kwargs):
        try:
            chunk = request.data[self.field_name]
        except KeyError:
            raise ChunkedUploadError(status=status.HTTP_400_BAD_REQUEST,
                                     detail='No chunk file was submitted')

        if whole:
            start = 0
            total = chunk.size
            end = total - 1
        else:
            content_range = request.META.get('HTTP_CONTENT_RANGE', '')
            match = self.content_range_pattern.match(content_range)
            if not match:
                raise ChunkedUploadError(status=status.HTTP_400_BAD_REQUEST,
                                         detail='Error in request headers')

            start = int(match.group('start'))
            end = int(match.group('end'))
            total = int(match.group('total'))

        chunk_size = end - start + 1
        max_bytes = self.get_max_bytes(request)

        if end > total:
            raise ChunkedUploadError(
                status=status.HTTP_400_BAD_REQUEST,
                detail='End of chunk exceeds reported total (%s bytes)' % total
            )

        if max_bytes is not None and total > max_bytes:
            raise ChunkedUploadError(
                status=status.HTTP_400_BAD_REQUEST,
                detail='Size of file exceeds the limit (%s bytes)' % max_bytes
            )

        if chunk.size != chunk_size:
            raise ChunkedUploadError(
                status=status.HTTP_400_BAD_REQUEST,
                detail="File size doesn't match headers: file size is {} but {} reported".format(
                    chunk.size,
                    chunk_size,
                ),
            )

        if pk:
            upload_id = pk
            chunked_upload = get_object_or_404(self.get_queryset(),
                                               pk=upload_id)
            self.is_valid_chunked_upload(chunked_upload)
            if chunked_upload.offset != start:
                raise ChunkedUploadError(
                    status=status.HTTP_400_BAD_REQUEST,
                    detail='Offsets do not match',
                    expected_offset=chunked_upload.offset,
                    provided_offset=start,
                )

            chunked_upload.append_chunk(chunk, chunk_size=chunk_size)
        else:
            kwargs = {'offset': chunk.size}
            if hasattr(self.model, self.user_field_name):
                if hasattr(request, 'user') and request.user.is_authenticated:
                    kwargs[self.user_field_name] = request.user
                elif self.model._meta.get_field(self.user_field_name).null:
                    kwargs[self.user_field_name] = None
                else:
                    raise ChunkedUploadError(
                        status=status.HTTP_400_BAD_REQUEST,
                        detail="Upload requires user authentication but user cannot be determined",
                    )
            print(request.data)
            chunked_upload = self.serializer_class(data=request.data)
            if not chunked_upload.is_valid():
                raise ChunkedUploadError(status=status.HTTP_400_BAD_REQUEST,
                                         detail=chunked_upload.errors)

            # chunked_upload is currently a serializer;
            # save returns model instance
            chunked_upload = chunked_upload.save(**kwargs)

        return chunked_upload

    def on_completion(self, chunked_upload, request):
        return super().on_completion(chunked_upload, request)